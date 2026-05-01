import { PyWireApp } from '../core/app'
import { DOMUpdater } from '../core/dom-updater'
import { EventData } from '../core/transports'
import { logger } from '../core/logger'

// Type alias for backward compatibility
type Application = PyWireApp

type UploadResult = { _upload_id: string }
type FormDataValue = string | string[] | UploadResult | UploadResult[]

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
  private debouncers = new Map<string, number>()
  private throttlers = new Map<string, number>()
  private firedOnce = new Set<string>()

  private defaultEvents = ['click', 'submit', 'input', 'change']
  private attachedEvents = new Set<string>()

  // Events that should be suppressed during DOM updates to prevent loops
  private suppressDuringUpdate = ['focus', 'blur', 'mouseenter', 'mouseleave']

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
    this.attachListeners(this.defaultEvents)
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

    // --- 3. Performance Modifiers ---
    const debounceMod = modifiers.find((m) => m.startsWith('debounce'))
    const throttleMod = modifiers.find((m) => m.startsWith('throttle'))

    const elementId = element.id || this.getUniqueId(element)
    const eventKey = `${elementId}-${eventType}-${handlerName}`

    if (debounceMod) {
      const duration = this.parseDuration(modifiers, 250)

      if (this.debouncers.has(eventKey)) {
        window.clearTimeout(this.debouncers.get(eventKey))
      }

      const timer = window.setTimeout(() => {
        this.debouncers.delete(eventKey)
        void this.dispatchEvent(element, eventType, handlerName, e, explicitArgs)
      }, duration)

      this.debouncers.set(eventKey, timer)
      return
    }

    if (throttleMod) {
      const duration = this.parseDuration(modifiers, 250)
      if (this.throttlers.has(eventKey)) return

      this.throttlers.set(eventKey, Date.now())
      // Execute immediately
      void this.dispatchEvent(element, eventType, handlerName, e, explicitArgs)

      window.setTimeout(() => {
        this.throttlers.delete(eventKey)
      }, duration)
      return
    }

    // Direct dispatch
    void this.dispatchEvent(element, eventType, handlerName, e, explicitArgs)
  }

  /**
   * Extract data and send event.
   */
  private async dispatchEvent(
    element: HTMLElement,
    eventType: string,
    handler: string,
    e: Event,
    explicitArgs?: unknown[]
  ): Promise<void> {
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

      const formData = new FormData(element)
      const data: Record<string, FormDataValue> = {}
      const uploadFormData = new FormData()
      let hasFileUploads = false
      formData.forEach((value, key) => {
        if (value instanceof File) {
          if (value.size > 0) {
            uploadFormData.append(key, value)
            hasFileUploads = true
          }
          return
        }

        const strVal = value.toString()
        // Handle multiple values for same key
        if (data[key] !== undefined) {
          if (Array.isArray(data[key])) {
            ;(data[key] as string[]).push(strVal)
          } else {
            data[key] = [data[key] as string, strVal]
          }
        } else {
          data[key] = strVal
        }
      })

      if (hasFileUploads) {
        const uploadMap = await this.uploadFiles(uploadFormData, element)
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
