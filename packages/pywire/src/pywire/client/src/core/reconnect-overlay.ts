import { logger } from './logger'

/**
 * Reconnection overlay shown when the transport disconnects.
 *
 * Expects a `<template id="_pywire_reconnect">` injected by the server into
 * the page HTML. The server always provides one — either the user's custom
 * `__reconnect__.wire` template or the built-in default from
 * `templates/reconnect/default.html`.
 *
 * The root element exposes `data-pw-reconnect-state` ("reconnecting" | "failed")
 * so templates can style both states with CSS alone.
 *
 * Reconnection is driven by the transport layer (e.g. WebSocket auto-reconnect).
 * The transport calls `markFailed()` when it has exhausted its reconnect budget
 * — this overlay does NOT independently track attempts, so the visual state
 * stays in lockstep with whether the transport is still trying.
 */
export class ReconnectOverlay {
  private element: HTMLElement | null = null
  private enabled: boolean

  constructor(opts: { enabled?: boolean } = {}) {
    this.enabled = opts.enabled ?? true
  }

  /**
   * Show the overlay in its "reconnecting" state. Idempotent.
   */
  show(): void {
    if (!this.enabled) return
    this.ensureElement()
    if (!this.element) return
    this.element.style.display = ''
    this.setState('reconnecting')
  }

  /**
   * Switch the overlay into its "failed" state. Templates style this with
   * `[data-pw-reconnect-state="failed"]` (e.g. swap the spinner for a
   * Reload button). Called by the transport once it gives up.
   */
  markFailed(): void {
    if (!this.enabled) return
    this.ensureElement()
    if (!this.element) return
    this.element.style.display = ''
    this.setState('failed')
  }

  /**
   * Hide the overlay.
   */
  hide(): void {
    if (this.element) {
      this.element.style.display = 'none'
    }
  }

  /**
   * Clean up the overlay element completely.
   */
  destroy(): void {
    if (this.element) {
      this.element.remove()
      this.element = null
    }
  }

  // ---------------------------------------------------------------------------
  // Internal helpers
  // ---------------------------------------------------------------------------

  private setState(state: 'reconnecting' | 'failed'): void {
    if (!this.element) return
    this.element.setAttribute('data-pw-reconnect-state', state)
  }

  /**
   * Build or re-use the overlay DOM element.
   *
   * Expects a `<template id="_pywire_reconnect">` injected by the server.
   */
  private ensureElement(): void {
    // Re-create if removed from DOM (e.g. by PJAX morphdom update)
    if (this.element && !document.body.contains(this.element)) {
      this.element = null
    }
    if (this.element) return

    const tmpl = document.getElementById('_pywire_reconnect') as HTMLTemplateElement | null
    if (tmpl && tmpl.content) {
      const wrapper = document.createElement('div')
      wrapper.id = '_pywire_reconnect_overlay'
      wrapper.appendChild(tmpl.content.cloneNode(true))
      document.body.appendChild(wrapper)
      this.element = wrapper
      return
    }

    logger.warn('PyWire: No reconnect overlay template found in DOM')
  }
}
