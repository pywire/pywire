import { logger } from './logger'

/**
 * Reconnection overlay shown when the transport disconnects.
 *
 * Checks for a user-provided `<template id="_pywire_reconnect">` in the DOM.
 * If found, clones it as the overlay content. Otherwise uses a built-in default
 * with a spinner and "Reconnecting..." / "Connection lost" states.
 *
 * The root element exposes `data-pw-reconnect-state` ("reconnecting" | "failed")
 * so custom templates can style both states with CSS alone.
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
   */
  private ensureElement(): void {
    if (this.element) return

    // Check for user-provided template
    const tmpl = document.getElementById('_pywire_reconnect') as HTMLTemplateElement | null
    if (tmpl && tmpl.content) {
      const wrapper = document.createElement('div')
      wrapper.id = '_pywire_reconnect_overlay'
      wrapper.appendChild(tmpl.content.cloneNode(true))
      document.body.appendChild(wrapper)
      this.element = wrapper
      return
    }

    // Built-in default overlay
    this.element = document.createElement('div')
    this.element.id = '_pywire_reconnect_overlay'
    this.element.innerHTML = DEFAULT_OVERLAY_HTML
    document.body.appendChild(this.element)

    // Inject default styles (once)
    if (!document.getElementById('_pywire_reconnect_styles')) {
      const style = document.createElement('style')
      style.id = '_pywire_reconnect_styles'
      style.textContent = DEFAULT_OVERLAY_CSS
      document.head.appendChild(style)
    }
  }
}

// ---------------------------------------------------------------------------
// Built-in default overlay markup & styles
// ---------------------------------------------------------------------------

const DEFAULT_OVERLAY_HTML = `
<div class="pw-reconnect-backdrop">
  <div class="pw-reconnect-card">
    <div class="pw-reconnect-spinner" aria-hidden="true"></div>
    <p class="pw-reconnect-message pw-reconnect-msg-reconnecting">Reconnecting&hellip;</p>
    <p class="pw-reconnect-message pw-reconnect-msg-failed">Connection lost</p>
    <button class="pw-reconnect-reload" onclick="location.reload()">Reload</button>
  </div>
</div>
`

const DEFAULT_OVERLAY_CSS = `
/* PyWire reconnect overlay – customise via CSS custom properties */
#_pywire_reconnect_overlay {
  --pw-reconnect-backdrop: rgba(0, 0, 0, 0.45);
  --pw-reconnect-card-bg: #fff;
  --pw-reconnect-card-shadow: 0 4px 24px rgba(0, 0, 0, 0.18);
  --pw-reconnect-text: #222;
  --pw-reconnect-muted: #888;
  --pw-reconnect-accent: #3b82f6;
  --pw-reconnect-btn-bg: #3b82f6;
  --pw-reconnect-btn-text: #fff;
}

@media (prefers-color-scheme: dark) {
  #_pywire_reconnect_overlay {
    --pw-reconnect-backdrop: rgba(0, 0, 0, 0.6);
    --pw-reconnect-card-bg: #1e1e2e;
    --pw-reconnect-card-shadow: 0 4px 24px rgba(0, 0, 0, 0.4);
    --pw-reconnect-text: #e0e0e0;
    --pw-reconnect-muted: #999;
  }
}

#_pywire_reconnect_overlay .pw-reconnect-backdrop {
  position: fixed;
  inset: 0;
  z-index: 99999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--pw-reconnect-backdrop);
}

#_pywire_reconnect_overlay .pw-reconnect-card {
  background: var(--pw-reconnect-card-bg);
  box-shadow: var(--pw-reconnect-card-shadow);
  border-radius: 12px;
  padding: 2rem 2.5rem;
  text-align: center;
  font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  color: var(--pw-reconnect-text);
  max-width: 340px;
  width: 90vw;
}

/* Spinner */
#_pywire_reconnect_overlay .pw-reconnect-spinner {
  width: 36px;
  height: 36px;
  margin: 0 auto 1rem;
  border: 3px solid var(--pw-reconnect-muted);
  border-top-color: var(--pw-reconnect-accent);
  border-radius: 50%;
  animation: pw-spin 0.8s linear infinite;
}

@keyframes pw-spin {
  to { transform: rotate(360deg); }
}

/* Messages */
#_pywire_reconnect_overlay .pw-reconnect-message {
  margin: 0 0 0.5rem;
  font-size: 1rem;
  line-height: 1.4;
}

/* State-driven visibility */
#_pywire_reconnect_overlay .pw-reconnect-msg-failed,
#_pywire_reconnect_overlay .pw-reconnect-reload {
  display: none;
}

#_pywire_reconnect_overlay[data-pw-reconnect-state="failed"] .pw-reconnect-spinner,
#_pywire_reconnect_overlay[data-pw-reconnect-state="failed"] .pw-reconnect-msg-reconnecting {
  display: none;
}

#_pywire_reconnect_overlay[data-pw-reconnect-state="failed"] .pw-reconnect-msg-failed,
#_pywire_reconnect_overlay[data-pw-reconnect-state="failed"] .pw-reconnect-reload {
  display: block;
}

/* Reload button */
#_pywire_reconnect_overlay .pw-reconnect-reload {
  margin-top: 1rem;
  padding: 0.5rem 1.5rem;
  border: none;
  border-radius: 6px;
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
  background: var(--pw-reconnect-btn-bg);
  color: var(--pw-reconnect-btn-text);
  transition: opacity 0.15s;
}

#_pywire_reconnect_overlay .pw-reconnect-reload:hover {
  opacity: 0.85;
}
`
