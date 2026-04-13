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
 * This overlay tracks elapsed attempts on an exponential-backoff schedule and
 * transitions to "failed" after `maxAttempts` intervals have elapsed without
 * the connection being restored.
 */
export class ReconnectOverlay {
  private element: HTMLElement | null = null
  private maxAttempts: number
  private enabled: boolean
  private attemptCount = 0
  private failTimer: ReturnType<typeof setTimeout> | null = null

  constructor(opts: { maxAttempts?: number; enabled?: boolean } = {}) {
    this.maxAttempts = opts.maxAttempts ?? 10
    this.enabled = opts.enabled ?? true
  }

  /**
   * Show the overlay and begin tracking reconnection attempts.
   * The transport layer handles actual reconnection; this overlay
   * provides visual feedback and gives up after maxAttempts.
   */
  show(): void {
    if (!this.enabled) return
    this.attemptCount = 0
    this.ensureElement()
    if (!this.element) return
    this.element.style.display = ''
    this.setState('reconnecting')
    this.scheduleFailCheck()
  }

  /**
   * Hide the overlay and cancel any pending fail timer.
   */
  hide(): void {
    this.cancelTimer()
    if (this.element) {
      this.element.style.display = 'none'
    }
  }

  /**
   * Clean up the overlay element completely.
   */
  destroy(): void {
    this.cancelTimer()
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

  private cancelTimer(): void {
    if (this.failTimer !== null) {
      clearTimeout(this.failTimer)
      this.failTimer = null
    }
  }

  /**
   * Schedule the next "attempt" tick. Each tick increments the counter and,
   * if we've hit maxAttempts without the connection being restored, sets
   * the overlay state to "failed".
   */
  private scheduleFailCheck(): void {
    if (this.attemptCount >= this.maxAttempts) {
      this.setState('failed')
      logger.warn(`PyWire: Reconnection failed after ${this.maxAttempts} attempts`)
      return
    }

    // Exponential backoff: 1s, 2s, 4s, 8s, ..., capped at 30s
    const delay = Math.min(1000 * Math.pow(2, this.attemptCount), 30000)
    logger.log(
      `PyWire: Waiting for reconnection (attempt ${this.attemptCount + 1}/${this.maxAttempts}, next check in ${delay}ms)`
    )

    this.failTimer = setTimeout(() => {
      this.attemptCount++
      this.scheduleFailCheck()
    }, delay)
  }

  /**
   * Build or re-use the overlay DOM element.
   *
   * Expects a `<template id="_pywire_reconnect">` injected by the server.
   */
  private ensureElement(): void {
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
