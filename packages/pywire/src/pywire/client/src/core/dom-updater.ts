/**
 * DOM Updater using morphdom for efficient DOM diffing.
 */
import morphdom from 'morphdom'
import { logger } from './logger'

interface FocusState {
  /** CSS selector to find the element */
  selector: string
  /** Element ID if available */
  id: string | null
  tagName: string
  selectionStart: number | null
  selectionEnd: number | null
  scrollTop: number
  scrollLeft: number
  value: string
}

export class DOMUpdater {
  /**
   * Flag to indicate DOM is being updated.
   * Event handlers should check this to avoid triggering events during updates.
   */
  static isUpdating = false

  private debug: boolean

  constructor(debug: boolean = false) {
    this.debug = debug
  }

  setDebug(debug: boolean): void {
    this.debug = debug
  }

  /**
   * Generate a stable key for an element.
   * Used by morphdom to match elements between old and new DOM.
   */
  private getNodeKey(node: Node): string | undefined {
    if (!(node instanceof HTMLElement)) return undefined

    // 1. Use data-pw-key as key FIRST (explicitly stable across renders)
    if (node.hasAttribute('data-pw-key')) {
      return node.getAttribute('data-pw-key') || undefined
    }

    // 2. Use explicit ID (but skip client-generated pywire-uid-* IDs)
    if (node.id && !node.id.startsWith('pywire-uid-')) {
      return node.id
    }

    // 3. Use name attribute for form elements
    if (
      node instanceof HTMLInputElement ||
      node instanceof HTMLSelectElement ||
      node instanceof HTMLTextAreaElement
    ) {
      if (node.name) {
        return `${node.tagName}-name-${node.name}`
      }
    }

    // 4. For other elements, no key (morphdom will use position-based matching)
    return undefined
  }

  /**
   * Generate a selector to find an element
   */
  private getElementSelector(el: Element): string {
    if (el.id) return `#${el.id}`

    // Build a path-based selector
    const path: string[] = []
    let current: Element | null = el

    while (current && current !== document.body && path.length < 5) {
      let selector = current.tagName.toLowerCase()

      // Add distinguishing attributes
      if (current.id) {
        selector = `#${current.id}`
        path.unshift(selector)
        break // ID is unique enough
      }

      // Use name for form elements
      if (
        current instanceof HTMLInputElement ||
        current instanceof HTMLSelectElement ||
        current instanceof HTMLTextAreaElement
      ) {
        if (current.name) {
          selector += `[name="${current.name}"]`
        }
      }

      // Use data-on-* for event elements
      for (const attr of current.attributes) {
        if (attr.name.startsWith('data-on-')) {
          selector += `[${attr.name}="${attr.value}"]`
          break
        }
      }

      // Add nth-child for disambiguation
      if (current.parentElement) {
        const sibs = Array.from(current.parentElement.children)
        const sameTags = sibs.filter((s) => s.tagName === current!.tagName)
        if (sameTags.length > 1) {
          const idx = sameTags.indexOf(current) + 1
          selector += `:nth-of-type(${idx})`
        }
      }

      path.unshift(selector)
      current = current.parentElement
    }

    return path.join(' > ')
  }

  /**
   * Capture the current focus state before updating.
   */
  private captureFocusState(): FocusState | null {
    const active = document.activeElement
    if (!active || active === document.body || active === document.documentElement) return null

    const state: FocusState = {
      selector: this.getElementSelector(active),
      id: active.id || null,
      tagName: active.tagName,
      selectionStart: null,
      selectionEnd: null,
      scrollTop: 0,
      scrollLeft: 0,
      value: '',
    }

    if (active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement) {
      state.selectionStart = active.selectionStart
      state.selectionEnd = active.selectionEnd
      state.scrollTop = active.scrollTop
      state.scrollLeft = active.scrollLeft
      if (!(active instanceof HTMLInputElement && active.type === 'file')) {
        state.value = active.value
      }
    }

    return state
  }

  /**
   * Restore focus state after updating.
   */
  private restoreFocusState(state: FocusState | null): void {
    if (!state) return

    // Try to find by ID first, then by selector
    let el: Element | null = null
    if (state.id) {
      el = document.getElementById(state.id)
    }
    if (!el && state.selector) {
      try {
        el = document.querySelector(state.selector)
      } catch {
        // Invalid selector, skip
      }
    }

    if (!el) return // Restore focus
    ;(el as HTMLElement).focus()

    // Restore selection/caret position
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
      // Restore value if it matches what we captured
      if (
        !(el instanceof HTMLInputElement && el.type === 'file') &&
        state.value &&
        el.value !== state.value
      ) {
        el.value = state.value
      }

      if (state.selectionStart !== null && state.selectionEnd !== null) {
        try {
          el.setSelectionRange(state.selectionStart, state.selectionEnd)
        } catch {
          // Some input types (date, number) don't support setSelectionRange
        }
      }
      el.scrollTop = state.scrollTop
      el.scrollLeft = state.scrollLeft
    }
  }

  private executeScripts(container: ParentNode): void {
    const scripts = container.querySelectorAll('script')
    scripts.forEach((oldScript) => {
      if (oldScript.src) {
        const newScript = document.createElement('script')
        // Copy all attributes
        Array.from(oldScript.attributes).forEach((attr) => {
          newScript.setAttribute(attr.name, attr.value)
        })
        document.head.appendChild(newScript)
      } else {
        // For inline scripts, use indirect eval to ensure global execution
        // This is more reliable in some test environments than appendChild
        const code = oldScript.textContent || ''
        if (code) {
          try {
            // Indirect eval runs in global scope
            const globalEval = eval
            globalEval(code)
          } catch (e) {
            logger.error('[DOMUpdater] Inline script execution failed:', e)
          }
        }
      }
    })
  }

  /**
   * Apply a DOM update using morphdom.
   */
  applyUpdate(target: Node, newContent: string | Node, childrenOnly: boolean = false): void {
    // Set flag to suppress focus/blur events during update
    DOMUpdater.isUpdating = true
    if (this.debug) {
      logger.log('[DOMUpdater] Starting update on', target.nodeName)
    }

    try {
      // Dispatch pre-update event on target
      target.dispatchEvent(
        new CustomEvent('pywire:preupdate', { bubbles: true, detail: { target } })
      )

      // Capture focus before morphdom runs
      const focusState = this.captureFocusState()

      let contentToMorph: Node = newContent as Node
      if (typeof newContent === 'string') {
        if (target.nodeName === 'HTML') {
          const parser = new DOMParser()
          const parsedDoc = parser.parseFromString(newContent, 'text/html')
          this.executeScripts(parsedDoc)
          contentToMorph = parsedDoc.documentElement
        } else {
          const tempContainer = document.createElement(target.nodeName === 'BODY' ? 'body' : 'div')
          tempContainer.innerHTML = newContent.trim()
          this.executeScripts(tempContainer)
          if (childrenOnly) {
            // If morphing children only, the container itself is passed to morphdom.
            // morphdom will then diff target's children against tempContainer's children.
            contentToMorph = tempContainer
          } else {
            // Normal morph: take the first element from the fragment.
            // If the fragment is empty or just text, fallback to the container.
            contentToMorph = tempContainer.firstElementChild || tempContainer
          }
        }
      } else {
        // If newContent is already a Node, execute scripts within it.
        this.executeScripts(newContent as Element)
      }

      if (morphdom) {
        try {
          morphdom(target, contentToMorph as any, {
            childrenOnly,
            // Custom key function for stable element matching
            getNodeKey: (node: Node) => this.getNodeKey(node),

            onElUpdated: (el) => {
              el.dispatchEvent(new CustomEvent('pywire:update', { bubbles: true, detail: { el } }))
            },

            onBeforeElUpdated: (fromEl, toEl) => {
              // Transfer ALL relevant state from old element to new element

              // Input/Textarea: preserve value ONLY if they are broadly similar
              // (e.g. user is still typing or deleted a few chars).
              // If the server sends a completely different value, let it win.
              if (fromEl instanceof HTMLInputElement && toEl instanceof HTMLInputElement) {
                if (fromEl.type === 'file' || toEl.type === 'file') {
                  // Keep the existing file input node to avoid clearing selected files.
                  // morphdom's default property sync can assign fromEl.value = toEl.value ("")
                  // which clears browser file selections.
                  for (const attr of Array.from(toEl.attributes)) {
                    if (fromEl.getAttribute(attr.name) !== attr.value) {
                      fromEl.setAttribute(attr.name, attr.value)
                    }
                  }
                  for (const attr of Array.from(fromEl.attributes)) {
                    if (!toEl.hasAttribute(attr.name)) {
                      fromEl.removeAttribute(attr.name)
                    }
                  }
                  return false
                }
                if (fromEl.type === 'checkbox' || fromEl.type === 'radio') {
                  toEl.checked = fromEl.checked
                } else {
                  const s = toEl.value || ''
                  const c = fromEl.value || ''
                  if (c.startsWith(s) || s.startsWith(c)) {
                    toEl.value = c
                  }
                }
              }

              if (fromEl instanceof HTMLTextAreaElement && toEl instanceof HTMLTextAreaElement) {
                const s = toEl.value || ''
                const c = fromEl.value || ''
                if (c.startsWith(s) || s.startsWith(c)) {
                  toEl.value = c
                }
              }

              // Select: preserve selected option
              if (fromEl instanceof HTMLSelectElement && toEl instanceof HTMLSelectElement) {
                // Preserve by value (more robust than index)
                if (
                  fromEl.value &&
                  Array.from(toEl.options).some((o: any) => o.value === fromEl.value)
                ) {
                  toEl.value = fromEl.value
                } else if (
                  fromEl.selectedIndex >= 0 &&
                  fromEl.selectedIndex < toEl.options.length
                ) {
                  toEl.selectedIndex = fromEl.selectedIndex
                }
              }

              // Preserve client-generated IDs (vital for debouncers/throttlers that key off ID)
              if (fromEl.id && fromEl.id.startsWith('pywire-uid-') && !toEl.id) {
                toEl.id = fromEl.id
              }

              return true
            },

            onBeforeElChildrenUpdated: (fromEl, _toEl) => {
              // If element is marked as permanent, skip updating its children
              if (fromEl instanceof HTMLElement && fromEl.hasAttribute('data-pw-permanent')) {
                if (this.debug) {
                  logger.log('[DOMUpdater] Permanent element detected, skipping children:', fromEl)
                }
                return false
              }
              return true
            },

            onBeforeNodeDiscarded: (node) => {
              // Preserve explicitly marked permanent elements
              if (node instanceof Element && node.hasAttribute('data-pw-permanent')) {
                return false
              }

              // Only preserve PyWire core scripts automatically. Let app-level SCRIPT, STYLE, LINK
              // be discarded if they aren't in the new HTML, to avoid accumulating old tags.
              if (node.nodeName === 'SCRIPT') {
                const id = (node as Element).id
                const src = (node as HTMLScriptElement).src
                if (id === '_pywire_spa_meta' || (src && src.includes('pywire.core'))) {
                  return false
                }
              }
              return true
            },
          })
        } catch (e) {
          logger.error('Morphdom failed:', e)
          if (target === document.documentElement && typeof newContent === 'string') {
            document.open()
            document.write(newContent)
            document.close()
          }
        }

        // Restore focus after morphdom completes
        this.restoreFocusState(focusState)

        // Dispatch post-update event on target
        target.dispatchEvent(
          new CustomEvent('pywire:postupdate', { bubbles: true, detail: { target } })
        )
      } else if (target === document.documentElement && typeof newContent === 'string') {
        document.open()
        document.write(newContent)
        document.close()
      }
    } finally {
      // Clear flag after a microtask to ensure all focus events are suppressed
      setTimeout(() => {
        DOMUpdater.isUpdating = false
      }, 0)
    }
  }

  /**
   * Update the DOM with new HTML content.
   */
  update(newHtml: string): void {
    // Full document: starts with <!DOCTYPE or <html
    const hasHtmlRoot = /^\s*(<!DOCTYPE|<html)/i.test(newHtml)

    if (hasHtmlRoot) {
      this.applyUpdate(document.documentElement, newHtml)
      return
    }

    // Check if it's a raw un-wrapped list of elements representing body contents
    let body = document.body
    if (!body) {
      body = document.createElement('body')
      document.documentElement.appendChild(body)
    }
    // Morph body's children Only to prevent duplicating the body element itself
    // or disrupting attributes/scripts that are not managed by PyWire.
    this.applyUpdate(body, newHtml, true)
  }

  /**
   * Update a specific region by its region id.
   */
  updateRegion(regionId: string, regionHtml: string): void {
    const target = document.querySelector(`[data-pw-region="${regionId}"]`)
    if (!target) {
      if (this.debug) {
        logger.warn('[DOMUpdater] Region not found:', regionId)
      }
      return
    }
    this.applyUpdate(target, regionHtml)
    // Ensure the region anchor remains even if the server HTML omitted it.
    if (!target.getAttribute('data-pw-region')) {
      target.setAttribute('data-pw-region', regionId)
    }
  }
}
