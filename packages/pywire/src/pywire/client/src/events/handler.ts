import { PyWireApp } from '../core/app'
import { DOMUpdater } from '../core/dom-updater'
import { EventData } from '../core/transports'
import { logger } from '../core/logger'
import { beginSubmit, isBoundForm, releaseForms } from './forms'
import { applyOptimistic, isOptimistic, revertElement } from './pending'
import { schedulePolls } from './poll'

// Type alias for backward compatibility
type Application = PyWireApp

type UploadResult = { _upload_id: string }
type FormDataValue = string | string[] | UploadResult | UploadResult[]

type Timing = { kind: 'immediate' } | { kind: 'debounce' | 'throttle'; ms: number }

/**
 * Timing for events written without `.debounce`, `.throttle` or `.immediate`.
 * `input` applies to text-like controls only; checkboxes, selects and the
 * like send at once. `PyWire(event_defaults=...)` overrides entries.
 */
const DEFAULT_TIMING: Record<string, string> = {
  input: 'debounce.250ms',
  scroll: 'throttle.100ms',
  wheel: 'throttle.100ms',
  resize: 'throttle.100ms',
  mousemove: 'throttle.100ms',
  pointermove: 'throttle.100ms',
  touchmove: 'throttle.100ms',
  drag: 'throttle.100ms',
}
const TEXT_INPUT_TYPES = new Set(['text', 'email', 'search', 'url', 'tel', 'password', 'number'])

function isTextLike(el: EventTarget | null): boolean {
  if (el instanceof HTMLTextAreaElement) return true
  if (el instanceof HTMLInputElement) return TEXT_INPUT_TYPES.has(el.type)
  return el instanceof HTMLElement && el.isContentEditable
}

// Event base class metadata — serializable but useless noise on every Event.
// These never change since they're the Event interface itself.
const SKIP_EVENT_META = new Set([
  'type',
  'bubbles',
  'cancelable',
  'composed',
  'eventPhase',
  'isTrusted',
  'defaultPrevented',
  'cancelBubble',
  'returnValue',
  'timeStamp',
])

export class UnifiedEventHandler {
  private app: Application
  // Pending debounced sends and throttle windows, keyed per element, event
  // and handler. Both flush before any event that sends at once, in order,
  // so a handler never reads state from before the user's last keystroke.
  private debouncers = new Map<string, { timer: number; run: () => void }>()
  private throttlers = new Map<string, { timer: number; trailing: (() => void) | null }>()
  private firedOnce = new Set<string>()
  // Fields the user has typed in, per bound form: they validate on blur.
  private dirtyFields = new WeakMap<HTMLFormElement, Set<string>>()

  private defaultEvents = ['click', 'submit', 'input', 'change']
  private attachedEvents = new Set<string>()

  // Events that should be suppressed during DOM updates to prevent loops
  private suppressDuringUpdate = ['focus', 'blur', 'focusout', 'mouseenter', 'mouseleave']

  private static ENABLE_TRACE = false

  constructor(app: Application) {
    this.app = app
  }

  private debugLog(...args: unknown[]): void {
    if (UnifiedEventHandler.ENABLE_TRACE) {
      logger.log(...args)
    }
  }

  /**
   * Initialize global event listeners.
   * Uses event delegation on document body.
   */
  init(): void {
    // focusout drives live validation of bound forms.
    this.attachListeners([...this.defaultEvents, 'focusout'])
    this.refreshListeners()
  }

  /**
   * Scan DOM for data-on-* attributes and attach missing listeners.
   */
  refreshListeners(): void {
    const eventTypes = new Set<string>()
    // Scan all elements for data-on-* attributes
    // Optimization: only scan elements with at least one attribute
    const elements = document.querySelectorAll('*')
    elements.forEach((el) => {
      for (let i = 0; i < el.attributes.length; i++) {
        const attr = el.attributes[i]
        if (attr.name.startsWith('data-on-')) {
          eventTypes.add(attr.name.replace('data-on-', ''))
        }
      }
    })

    this.attachListeners(Array.from(eventTypes))
    // @poll timers ride the same lifecycle: (re)schedule newly mounted
    // poll elements and clear timers for unmounted / region-replaced ones.
    schedulePolls(this.app)
  }

  /**
   * Attach listeners for a list of event types if not already attached.
   */
  private attachListeners(eventTypes: string[]): void {
    eventTypes.forEach((eventType) => {
      if (this.attachedEvents.has(eventType)) return

      const options =
        eventType === 'mouseenter' ||
        eventType === 'mouseleave' ||
        eventType === 'focus' ||
        eventType === 'blur' ||
        eventType === 'scroll'
          ? { capture: true } // These don't bubble nicely or at all in some cases
          : undefined

      document.addEventListener(eventType, (e) => this.handleEvent(e), options)
      this.attachedEvents.add(eventType)
      this.debugLog('[Handler] Attached listener for:', eventType)
    })
  }

  /**
   * Helper to parse handlers from element (legacy or multiple/JSON).
   */
  private getHandlers(
    element: HTMLElement,
    eventType: string
  ): Array<{ name: string; modifiers: string[]; args?: unknown[] }> {
    const handlerAttr = `data-on-${eventType}`
    const attrValue = element.getAttribute(handlerAttr)
    if (!attrValue) return []

    if (attrValue.trim().startsWith('[')) {
      try {
        const handlers = JSON.parse(attrValue) as unknown
        if (Array.isArray(handlers)) {
          return handlers.flatMap((handler) => {
            if (!handler || typeof handler !== 'object') return []
            const name =
              'handler' in handler && typeof handler.handler === 'string' ? handler.handler : null
            if (!name) return []

            const modifiers =
              'modifiers' in handler && Array.isArray(handler.modifiers)
                ? handler.modifiers.filter((m: unknown): m is string => typeof m === 'string')
                : []

            const args = 'args' in handler && Array.isArray(handler.args) ? handler.args : undefined

            return [{ name, modifiers, args }]
          })
        }
      } catch (e) {
        logger.error('Error parsing event handlers:', e)
      }
    } else {
      // Legacy single handler
      const modifiersAttr = element.getAttribute(`data-modifiers-${eventType}`)
      const modifiers = modifiersAttr ? modifiersAttr.split(' ').filter((m) => m) : []
      return [{ name: attrValue, modifiers, args: undefined }]
    }
    return []
  }

  /**
   * Main event handler.
   */
  private async handleEvent(e: Event): Promise<void> {
    // Per-page !no_interactive opt-out. The flag may flip between SPA
    // navigations, so check at dispatch time. The handler stays attached
    // (cheap) but we ignore events while the current page declares itself
    // non-interactive.
    if (this.app.getConfig().pageInteractive === false) {
      return
    }

    const eventType = e.type

    // File inputs can retain a prior custom validity error unless we clear it
    // immediately when the user re-selects a file, even without data-on-change.
    if (
      eventType === 'change' &&
      e.target instanceof HTMLInputElement &&
      e.target.type === 'file'
    ) {
      e.target.setCustomValidity('')
    }

    // Skip focus/blur/mouseenter/mouseleave events during DOM updates to prevent loops
    if (DOMUpdater.isUpdating && this.suppressDuringUpdate.includes(eventType)) {
      this.debugLog(
        '[Handler] SUPPRESSING event during update:',
        eventType,
        'isUpdating=',
        DOMUpdater.isUpdating
      )
      return
    }

    this.debugLog('[Handler] Processing event:', eventType, 'isUpdating=', DOMUpdater.isUpdating)

    // Skip events already handled server-side via dispatch() interception.
    // The server called the Python handler directly and marked the CustomEvent
    // so we don't re-send it back to the server (which would double-execute).
    if ((e as unknown as Record<string, unknown>).__pwServerHandled) {
      this.debugLog('[Handler] Skipping server-handled dispatch event:', eventType)
      return
    }

    if (eventType === 'input' || eventType === 'change' || eventType === 'focusout') {
      this.liveValidate(e)
    }

    // 1. Delegated handlers (standard path walk with bubbling)
    const path = e.composedPath ? e.composedPath() : []
    let propagationStopped = false

    for (const node of path) {
      if (propagationStopped) break

      if (node instanceof HTMLElement) {
        const element = node
        const handlers = this.getHandlers(element, eventType)

        if (handlers.length > 0) {
          this.debugLog('[handleEvent] Found handlers on', element.tagName, handlers)

          for (const h of handlers) {
            // Skip if it's a .window or .outside handler - those are handled globally
            if (!h.modifiers.includes('window') && !h.modifiers.includes('outside')) {
              this.processEvent(element, eventType, h.name, h.modifiers, e, h.args)
              if (e.cancelBubble) propagationStopped = true
            }
          }
        }
      }
    }

    // 2. Global handlers (.window, .outside)
    this.handleGlobalEvent(e)
  }

  /**
   * Handle modifiers that listen outside the normal delegation path.
   */
  private handleGlobalEvent(e: Event): void {
    const eventType = e.type
    const windowSelector = `[data-modifiers-${eventType}*="window"]`
    const outsideSelector = `[data-modifiers-${eventType}*="outside"]`

    const candidates = document.querySelectorAll(`${windowSelector}, ${outsideSelector}`)

    candidates.forEach((el) => {
      if (!(el instanceof HTMLElement)) return

      const handlers = this.getHandlers(el, eventType)
      for (const h of handlers) {
        // .window: trigger regardless of where the event happened
        if (h.modifiers.includes('window')) {
          this.processEvent(el, eventType, h.name, h.modifiers, e, h.args)
        }

        // .outside: trigger if target is NOT inside this element
        if (h.modifiers.includes('outside')) {
          const target = e.target as Node | null
          if (target && !el.contains(target)) {
            this.processEvent(el, eventType, h.name, h.modifiers, e, h.args)
          }
        }
      }
    })
  }

  /**
   * Process an event for a specific element after it has been matched.
   */
  private processEvent(
    element: HTMLElement,
    eventType: string,
    handlerName: string,
    modifiers: string[],
    e: Event,
    explicitArgs?: unknown[]
  ): void {
    this.debugLog('[processEvent]', eventType, 'handler:', handlerName, 'modifiers:', modifiers)

    // --- 1. Logic Modifers ---

    // .prevent
    if (modifiers.includes('prevent') || eventType === 'submit') {
      this.debugLog('[processEvent] Calling preventDefault')
      e.preventDefault()
    }

    // .stop
    if (modifiers.includes('stop')) {
      e.stopPropagation()
    }

    // .self
    if (modifiers.includes('self')) {
      if (e.target !== element) return
    }

    // .once
    if (modifiers.includes('once')) {
      const elementId = element.id || this.getUniqueId(element)
      const onceKey = `${elementId}-${eventType}-${handlerName}`
      if (this.firedOnce.has(onceKey)) return
      this.firedOnce.add(onceKey)
    }

    // --- 2. Filter Modifiers ---

    // System modifiers (Shift, Ctrl, Alt, Meta) - supported on Keyboard and Mouse events
    if (modifiers.includes('shift') && (!('shiftKey' in e) || !e.shiftKey)) return
    if (modifiers.includes('ctrl') && (!('ctrlKey' in e) || !e.ctrlKey)) return
    if (modifiers.includes('alt') && (!('altKey' in e) || !e.altKey)) return
    if (modifiers.includes('meta') && (!('metaKey' in e) || !e.metaKey)) return
    if (modifiers.includes('cmd') && (!('metaKey' in e) || !e.metaKey)) return

    if (e instanceof KeyboardEvent) {
      // Known key modifiers
      const knownKeys = ['enter', 'escape', 'space', 'tab', 'up', 'down', 'left', 'right']
      // System modifiers that should NOT be treated as key constraints
      const systemMods = [
        'shift',
        'ctrl',
        'alt',
        'meta',
        'cmd',
        'window',
        'outside',
        'prevent',
        'stop',
        'self',
        'once',
        'debounce',
        'throttle',
        'immediate',
      ]

      // Key modifiers are anything that's not a system mod and is either a known key or a single character
      const keyModifiers = modifiers.filter((m) => {
        if (systemMods.includes(m)) return false
        if (m.startsWith('debounce') || m.startsWith('throttle')) return false
        if (m.endsWith('ms')) return false // Duration like 500ms
        return knownKeys.includes(m) || m.length === 1
      })

      if (keyModifiers.length > 0) {
        const pressedKey = e.key.toLowerCase()
        this.debugLog('[processEvent] Key check. Pressed:', pressedKey, 'Modifiers:', keyModifiers)

        // Map for special keys
        const keyMap: Record<string, string> = {
          escape: 'escape',
          esc: 'escape',
          enter: 'enter',
          space: ' ',
          spacebar: ' ',
          ' ': ' ',
          tab: 'tab',
          up: 'arrowup',
          arrowup: 'arrowup',
          down: 'arrowdown',
          arrowdown: 'arrowdown',
          left: 'arrowleft',
          arrowleft: 'arrowleft',
          right: 'arrowright',
          arrowright: 'arrowright',
        }

        // Normalize the pressed key
        const normalizedPressedKey = keyMap[pressedKey] || pressedKey

        // Check if any key constraint matches
        let match = false
        for (const constraint of keyModifiers) {
          const targetKey = keyMap[constraint] || constraint
          this.debugLog(
            '[processEvent] Comparing constraint:',
            constraint,
            '->',
            targetKey,
            'vs',
            normalizedPressedKey,
            'code:',
            e.code
          )

          // Match against key (normalized)
          if (targetKey === normalizedPressedKey) {
            match = true
            break
          }

          // Fallback: match against code (e.g. 'h' matches 'KeyH')
          // This handles cases where modifiers change the key value (e.g. Alt+H -> ˙)
          if (e.code && e.code.toLowerCase() === `key${targetKey}`) {
            match = true
            break
          }
        }
        if (!match) {
          this.debugLog('[processEvent] No key match found.')
          return
        }
      }
    }

    // --- 3. Timing: debounce, throttle, or send now ---
    const elementId = element.id || this.getUniqueId(element)
    const eventKey = `${elementId}-${eventType}-${handlerName}`
    const send = (): void => {
      void this.dispatchEvent(element, eventType, handlerName, modifiers, e, explicitArgs)
    }
    this.schedule(eventKey, this.timingFor(eventType, modifiers, e.target), send)
  }

  /**
   * Run `send` now, after a debounce, or throttled (first and last event of
   * each window). Anything sent now flushes pending debounced and trailing
   * sends first, in the order they were queued.
   */
  schedule(key: string, timing: Timing, send: () => void): void {
    if (timing.kind === 'debounce') {
      const pending = this.debouncers.get(key)
      if (pending) window.clearTimeout(pending.timer)
      const timer = window.setTimeout(() => {
        this.debouncers.delete(key)
        send()
      }, timing.ms)
      // Re-insert so flush order follows the latest keystroke.
      this.debouncers.delete(key)
      this.debouncers.set(key, { timer, run: send })
      return
    }

    if (timing.kind === 'throttle') {
      const window_ = this.throttlers.get(key)
      if (window_) {
        window_.trailing = send
        return
      }
      send()
      this.openThrottleWindow(key, timing.ms)
      return
    }

    const own = this.debouncers.get(key)
    if (own) {
      window.clearTimeout(own.timer)
      this.debouncers.delete(key)
    }
    this.flushPending()
    send()
  }

  /**
   * Live validation for bound forms rendered with `data-pw-validate="blur"`:
   * a field the user typed in validates when it loses focus, then on every
   * (debounced) keystroke while it shows an error. Checkboxes, radios and
   * selects validate on change. The server validates the whole form and
   * shows errors only for fields the user has been through.
   */
  private liveValidate(e: Event): void {
    if (this.app.isInteractive === false) return
    const field = e.target
    if (
      !(
        field instanceof HTMLInputElement ||
        field instanceof HTMLSelectElement ||
        field instanceof HTMLTextAreaElement
      )
    ) {
      return
    }
    const form = field.form
    if (!form || form.dataset.pwValidate !== 'blur' || !field.name) return
    if (field instanceof HTMLInputElement && field.type === 'file') return
    const handler = this.getHandlers(form, 'submit')[0]?.name
    if (!handler) return

    let dirty = this.dirtyFields.get(form)
    if (!dirty) {
      dirty = new Set()
      this.dirtyFields.set(form, dirty)
    }
    const name = field.name
    const key = `validate:${this.getUniqueId(form)}:${name}`
    const send = (): void => this.sendValidate(form, handler, name)
    const textLike = isTextLike(field)

    if (e.type === 'input') {
      if (!textLike) return
      dirty.add(name)
      if (field.getAttribute('aria-invalid') === 'true') {
        this.schedule(key, this.timingFor('input', [], field), send)
      }
      return
    }
    if (e.type === 'change') {
      if (!textLike) this.schedule(key, { kind: 'immediate' }, send)
      return
    }
    if (textLike && dirty.has(name)) {
      this.schedule(key, { kind: 'immediate' }, send)
    }
  }

  private sendValidate(form: HTMLFormElement, handler: string, field: string): void {
    this.app.sendEvent(handler, {
      type: 'validate',
      id: form.id || undefined,
      tagName: form.tagName,
      args: {},
      field,
      formData: this.formFields(form).data,
    })
  }

  /** A form's fields as the server reads them: repeated names become lists. */
  private formFields(form: HTMLFormElement): {
    data: Record<string, FormDataValue>
    files: FormData | null
  } {
    const data: Record<string, FormDataValue> = {}
    const files = new FormData()
    let hasFiles = false
    new FormData(form).forEach((value, key) => {
      if (value instanceof File) {
        if (value.size > 0) {
          files.append(key, value)
          hasFiles = true
        }
        return
      }
      const strVal = value.toString()
      const existing = data[key]
      if (existing === undefined) {
        data[key] = strVal
      } else if (Array.isArray(existing)) {
        ;(existing as string[]).push(strVal)
      } else {
        data[key] = [existing as string, strVal]
      }
    })
    return { data, files: hasFiles ? files : null }
  }

  private openThrottleWindow(key: string, ms: number): void {
    const state = { timer: 0, trailing: null as (() => void) | null }
    state.timer = window.setTimeout(() => {
      this.throttlers.delete(key)
      const trailing = state.trailing
      if (trailing) {
        trailing()
        this.openThrottleWindow(key, ms)
      }
    }, ms)
    this.throttlers.set(key, state)
  }

  /** Send every pending debounced and trailing throttled event now. */
  flushPending(): void {
    const debounced = Array.from(this.debouncers.values())
    this.debouncers.clear()
    for (const pending of debounced) {
      window.clearTimeout(pending.timer)
      pending.run()
    }
    for (const state of this.throttlers.values()) {
      const trailing = state.trailing
      state.trailing = null
      if (trailing) trailing()
    }
  }

  private timingFor(eventType: string, modifiers: string[], target: EventTarget | null): Timing {
    const explicit = this.timingFromModifiers(modifiers, 250)
    if (explicit) return explicit
    if (eventType === 'input' && target instanceof HTMLInputElement && target.type === 'range') {
      return { kind: 'throttle', ms: 100 }
    }
    if (eventType === 'input' && !isTextLike(target)) return { kind: 'immediate' }
    const configured = this.app.getConfig().eventDefaults?.[eventType]
    const spec = configured ?? DEFAULT_TIMING[eventType]
    if (!spec) return { kind: 'immediate' }
    return this.timingFromModifiers(spec.split('.'), 100) ?? { kind: 'immediate' }
  }

  private timingFromModifiers(modifiers: string[], fallbackMs: number): Timing | null {
    if (modifiers.includes('immediate')) return { kind: 'immediate' }
    if (modifiers.some((m) => m.startsWith('debounce'))) {
      return { kind: 'debounce', ms: this.parseDuration(modifiers, fallbackMs) }
    }
    if (modifiers.some((m) => m.startsWith('throttle'))) {
      return { kind: 'throttle', ms: this.parseDuration(modifiers, fallbackMs) }
    }
    return null
  }

  /**
   * Extract data and send event.
   */
  private async dispatchEvent(
    element: HTMLElement,
    eventType: string,
    handler: string,
    modifiers: string[],
    e: Event,
    explicitArgs?: unknown[]
  ): Promise<void> {
    // Double-submit guard: while an optimistic response is pending, the control
    // carries `data-pw-pending`. Ignore re-dispatches until the next update or
    // error clears it (see pending.ts).
    if (element.hasAttribute('data-pw-pending')) {
      this.debugLog('[Handler] Ignoring dispatch — element pending optimistic response')
      return
    }

    // Non-interactive mode: a form submit always goes through httpFormSubmit
    // (fetch + morph), regardless of any event-data field mask. The mask
    // controls what gets sent over a persistent channel via `sendEvent`;
    // it should not block the actual form POST.
    if (
      this.app.isInteractive === false &&
      eventType === 'submit' &&
      element instanceof HTMLFormElement
    ) {
      if (!this.validateFileInputs(element)) {
        return
      }
      if (isBoundForm(element) && !beginSubmit(element)) return
      // Apply the optimistic prediction (and its double-submit guard) before
      // the async POST. httpFormSubmit reconciles it: every failure mode
      // navigates away, success morphs + clearPending().
      if (isOptimistic(modifiers)) {
        applyOptimistic(element, modifiers)
      }
      await this.app.httpFormSubmit(element, handler)
      return
    }

    // Merge explicit args (from JSON) into args payload
    let args: Record<string, unknown> = {}
    if (explicitArgs && explicitArgs.length > 0) {
      explicitArgs.forEach((val, i) => {
        args[`arg${i}`] = val
      })
    } else {
      args = this.getArgs(element)
    }

    // Check for field mask — if present, only send listed fields.
    // null = attribute absent (no mask, send all fields)
    // empty string = attribute present but empty (send no event-specific fields)
    const fieldMaskAttr = element.getAttribute(`data-pw-fields-${eventType}`)
    const allowedFields =
      fieldMaskAttr !== null ? new Set(fieldMaskAttr.split(',').filter((f) => f)) : null

    const eventData: EventData = {
      type: eventType,
      id: element.id || undefined,
      name: (element as HTMLElement & { name?: string }).name || undefined,
      tagName: element.tagName,
      args: args,
    }

    // Attach ref info if present
    const refId = element.getAttribute('data-pw-ref')
    if (refId) {
      eventData.refId = refId
      const refData = this.app.getRefManager().getRefData(refId)
      Object.assign(eventData, refData)
    }

    // Extract specific data based on element type (reads from DOM element, not event)
    if (
      !allowedFields ||
      allowedFields.has('value') ||
      allowedFields.has('inputType') ||
      allowedFields.has('checked')
    ) {
      if (element instanceof HTMLInputElement) {
        if (!allowedFields || allowedFields.has('value')) {
          if (element.type === 'file') {
            eventData.value = Array.from(element.files ?? []).map((file) => ({
              name: file.name,
              size: file.size,
              type: file.type,
            }))
          } else {
            eventData.value = element.value
          }
        }
        if (!allowedFields || allowedFields.has('inputType')) {
          eventData.inputType = element.type
        }
        if (
          (!allowedFields || allowedFields.has('checked')) &&
          (element.type === 'checkbox' || element.type === 'radio')
        ) {
          eventData.checked = element.checked
        }
      } else if (element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement) {
        if (!allowedFields || allowedFields.has('value')) {
          eventData.value = element.value
        }
        if (
          element instanceof HTMLSelectElement &&
          element.multiple &&
          (!allowedFields || allowedFields.has('values'))
        ) {
          eventData.values = Array.from(element.selectedOptions, (o) => o.value)
        }
      }
    }

    // Generic event property extraction — grabs all serializable properties
    // from the event object (KeyboardEvent, MouseEvent, WheelEvent, etc.)
    for (const key in e) {
      if (SKIP_EVENT_META.has(key)) continue
      if (key === key.toUpperCase() && key.length > 1) continue // Event constants (NONE, AT_TARGET, etc.)
      if (allowedFields && !allowedFields.has(key)) continue
      if (key in eventData) continue

      const val = (e as unknown as Record<string, unknown>)[key]
      if (val === null || val === undefined) continue

      const t = typeof val
      if (t === 'string' || t === 'number' || t === 'boolean') {
        eventData[key] = val
      } else if (t === 'object' && !(val instanceof Node) && !(val instanceof Window)) {
        try {
          JSON.stringify(val)
          eventData[key] = val
        } catch {
          /* not serializable, skip */
        }
      }
    }

    // Extract Form Data for submit
    if (
      (!allowedFields || allowedFields.has('formData')) &&
      eventType === 'submit' &&
      element instanceof HTMLFormElement
    ) {
      if (!this.validateFileInputs(element)) {
        return
      }
      // A bound form waits for the server's answer before it submits again.
      if (isBoundForm(element) && !beginSubmit(element)) return

      const { data, files: uploadFormData } = this.formFields(element)

      if (uploadFormData) {
        // Apply the optimistic prediction (and its double-submit guard)
        // synchronously, BEFORE the async upload starts — otherwise a slow
        // upload leaves the control unguarded and a second click kicks off a
        // second upload.
        if (isOptimistic(modifiers)) {
          applyOptimistic(element, modifiers)
        }
        let uploadMap: Record<string, UploadResult | UploadResult[]>
        try {
          uploadMap = await this.uploadFiles(uploadFormData, element)
        } catch (err) {
          // No server error event will arrive for a failed upload — undo the
          // prediction here so the control is never left stuck.
          revertElement(element)
          releaseForms()
          throw err
        }
        for (const [field, uploadValue] of Object.entries(uploadMap)) {
          data[field] = uploadValue
        }
      }
      eventData.formData = data

      // Non-interactive (SSR) mode: form POST → fetch + morph instead of
      // a browser POST, so reload doesn't surface the "confirm resubmission"
      // dialog and the swap feels SPA-like. Treat missing flag as interactive
      // (matches the server-side default and the existing mock-app pattern).
      if (this.app.isInteractive === false) {
        await this.app.httpFormSubmit(element, handler)
        return
      }
    }

    // Apply the optimistic prediction synchronously, immediately before send
    // (the marker check skips re-applying when it was set before a file upload).
    if (isOptimistic(modifiers) && !element.hasAttribute('data-pw-pending')) {
      applyOptimistic(element, modifiers)
    }

    this.app.sendEvent(handler, eventData)
  }

  private validateFileInputs(form: HTMLFormElement): boolean {
    const fileInputs = form.querySelectorAll('input[type="file"]')
    for (const input of fileInputs) {
      if (!(input instanceof HTMLInputElement)) {
        continue
      }
      if (input.dataset.pwFileInput === '1') {
        continue
      }

      input.setCustomValidity('')
      const files = input.files ? Array.from(input.files) : []

      const maxFilesRaw = input.dataset.maxFiles
      if (maxFilesRaw) {
        const maxFiles = Number.parseInt(maxFilesRaw, 10)
        if (!Number.isNaN(maxFiles) && maxFiles > 0 && files.length > maxFiles) {
          input.setCustomValidity(`At most ${maxFiles} files are allowed`)
          input.reportValidity()
          return false
        }
      }

      const minSizeRaw = input.dataset.minSize
      const maxSizeRaw = input.dataset.maxSize
      const minSize = minSizeRaw ? Number.parseInt(minSizeRaw, 10) : null
      const maxSize = maxSizeRaw ? Number.parseInt(maxSizeRaw, 10) : null
      if (
        (minSize !== null && Number.isNaN(minSize)) ||
        (maxSize !== null && Number.isNaN(maxSize))
      ) {
        continue
      }

      for (const file of files) {
        if (minSize !== null && minSize > 0 && file.size < minSize) {
          input.setCustomValidity(`File is too small (min ${minSize} bytes)`)
          input.reportValidity()
          return false
        }
        if (maxSize !== null && maxSize > 0 && file.size > maxSize) {
          const sizeMb = maxSize / (1024 * 1024)
          input.setCustomValidity(`File is too large (max ${sizeMb.toFixed(1)}MB)`)
          input.reportValidity()
          return false
        }
      }

      const allowedNames = input.dataset.allowedNames
      if (allowedNames) {
        let allowedRegex: RegExp | null = null
        try {
          allowedRegex = new RegExp(allowedNames.replace(/\\\\/g, '\\'))
        } catch {
          allowedRegex = null
        }

        if (allowedRegex) {
          for (const file of files) {
            if (allowedRegex.test(file.name)) {
              continue
            }
            input.setCustomValidity('Filename is not allowed')
            input.reportValidity()
            return false
          }
        }
      }
    }
    return true
  }

  private async uploadFiles(
    fileData: FormData,
    form?: HTMLFormElement
  ): Promise<Record<string, UploadResult | UploadResult[]>> {
    const token = (
      document.querySelector('meta[name="pywire-upload-token"]') as HTMLMetaElement | null
    )?.content
    if (!token) {
      throw new Error('Missing upload token. File uploads are not enabled for this page.')
    }

    const headers: Record<string, string> = {
      'X-Upload-Token': token,
    }
    const httpSession = (window as Window & { __PYWIRE_HTTP_SESSION?: string | null })
      .__PYWIRE_HTTP_SESSION
    if (typeof httpSession === 'string' && httpSession.length > 0) {
      headers['X-PyWire-Session'] = httpSession
    }

    const uploadUrl = `${this.app.mountPath || ''}/_pywire/upload`
    const response = await fetch(uploadUrl, {
      method: 'POST',
      headers,
      body: fileData,
      credentials: 'same-origin',
    })
    const payload = (await response.json()) as Record<string, unknown>
    if (!response.ok) {
      const uploadError = payload?.error || 'File upload failed'
      throw new Error(String(uploadError))
    }

    const uploadIds = (payload.uploads ?? payload) as Record<string, unknown>
    const result: Record<string, UploadResult | UploadResult[]> = {}
    const multipleFieldNames = new Set<string>()
    if (form) {
      form.querySelectorAll('input[type="file"][multiple][name]').forEach((input) => {
        if (input instanceof HTMLInputElement && input.name) {
          multipleFieldNames.add(input.name)
        }
      })
    }
    for (const [field, raw] of Object.entries(uploadIds)) {
      const isMultipleField = multipleFieldNames.has(field)
      if (Array.isArray(raw)) {
        result[field] = raw.map((uploadId: unknown) => ({ _upload_id: String(uploadId) }))
        continue
      }
      if (isMultipleField) {
        result[field] = [{ _upload_id: String(raw) }]
        continue
      }
      result[field] = { _upload_id: String(raw) }
    }
    return result
  }

  private parseDuration(modifiers: string[], defaultDuration: number): number {
    const debounceIdx = modifiers.findIndex((m) => m.startsWith('debounce'))
    const throttleIdx = modifiers.findIndex((m) => m.startsWith('throttle'))
    const idx = debounceIdx !== -1 ? debounceIdx : throttleIdx

    if (idx !== -1 && modifiers[idx + 1]) {
      const next = modifiers[idx + 1]
      if (next.endsWith('ms')) {
        const val = parseInt(next)
        if (!isNaN(val)) return val
      }
    }

    // Support hyphenated: debounce-500ms
    const mod = modifiers[idx]
    if (mod && mod.includes('-')) {
      const parts = mod.split('-')
      const val = parseInt(parts[1])
      if (!isNaN(val)) return val
    }

    return defaultDuration
  }

  private getUniqueId(element: HTMLElement): string {
    if (!element.id) {
      element.id = 'pywire-uid-' + Math.random().toString(36).substr(2, 9)
    }
    return element.id
  }

  private getArgs(element: Element): Record<string, unknown> {
    const args: Record<string, unknown> = {}
    if (element instanceof HTMLElement) {
      for (const key in element.dataset) {
        if (key.startsWith('arg')) {
          try {
            args[key] = JSON.parse(element.dataset[key] || 'null')
          } catch {
            args[key] = element.dataset[key]
          }
        }
      }
    }
    return args
  }
}
