import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReconnectOverlay } from './reconnect-overlay'

describe('ReconnectOverlay', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('uses the built-in overlay when the page has no custom template', () => {
    const overlay = new ReconnectOverlay()
    overlay.show()

    const root = document.getElementById('_pywire_reconnect_overlay')
    expect(root?.getAttribute('data-pw-reconnect-state')).toBe('reconnecting')
    expect(root?.querySelector('style')).not.toBeNull()
    expect(root?.querySelector('.pw-reconnect-card')).not.toBeNull()

    overlay.markFailed()
    expect(root?.getAttribute('data-pw-reconnect-state')).toBe('failed')
  })

  it('wires the built-in Reload button without an inline handler', () => {
    const reload = vi.fn()
    vi.stubGlobal('location', { ...window.location, reload })
    try {
      new ReconnectOverlay().markFailed()
      const button = document.querySelector<HTMLButtonElement>('.pw-reconnect-reload')
      expect(button?.getAttribute('onclick')).toBeNull()
      button?.click()
      expect(reload).toHaveBeenCalledOnce()
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('prefers the custom template injected by the server', () => {
    document.body.innerHTML =
      '<template id="_pywire_reconnect"><p class="mine">Hold on</p></template>'
    new ReconnectOverlay().show()

    const root = document.getElementById('_pywire_reconnect_overlay')
    expect(root?.querySelector('.mine')?.textContent).toBe('Hold on')
    expect(root?.querySelector('.pw-reconnect-card')).toBeNull()
  })

  it('stays hidden when disabled', () => {
    new ReconnectOverlay({ enabled: false }).show()
    expect(document.getElementById('_pywire_reconnect_overlay')).toBeNull()
  })
})
