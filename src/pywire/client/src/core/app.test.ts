import { describe, it, expect, vi, beforeEach } from 'vitest'
import { PyWireApp } from './app'

// Mock dependencies
vi.mock('./transport-manager', () => {
  return {
    TransportManager: vi.fn().mockImplementation(function () {
      return {
        onMessage: vi.fn(),
        onStatusChange: vi.fn(),
        connect: vi.fn(),
        send: vi.fn(),
        getActiveTransport: vi.fn().mockReturnValue('mock'),
        disconnect: vi.fn(),
      }
    }),
  }
})

vi.mock('./dom-updater', () => {
  return {
    DOMUpdater: vi.fn().mockImplementation(function () {
      return {
        update: vi.fn(),
        updateRegion: vi.fn(),
      }
    }),
  }
})

describe('PyWireApp', () => {
  let app: PyWireApp

  beforeEach(() => {
    vi.clearAllMocks()
    document.body.innerHTML = ''
    app = new PyWireApp({ autoInit: false })
  })

  it('should intercept link clicks for sibling paths', async () => {
    // Setup metadata
    const meta = document.createElement('script')
    meta.id = '_pywire_spa_meta'
    meta.textContent = JSON.stringify({ sibling_paths: ['/a'] })
    document.head.appendChild(meta)

    await app.init()

    const link = document.createElement('a')
    link.href = '/a'
    document.body.appendChild(link)

    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    const preventDefaultSpy = vi.spyOn(event, 'preventDefault')
    const navigateToSpy = vi.spyOn(app, 'navigateTo').mockImplementation(() => {})

    link.dispatchEvent(event)

    expect(preventDefaultSpy).toHaveBeenCalled()
    expect(navigateToSpy).toHaveBeenCalledWith('/a')
  })

  it('should NOT intercept link clicks with data-pywire-reload', async () => {
    // Setup metadata (enable pjax to make sure it would otherwise intercept)
    const meta = document.createElement('script')
    meta.id = '_pywire_spa_meta'
    meta.textContent = JSON.stringify({ enable_pjax: true })
    document.head.appendChild(meta)

    await app.init()

    const link = document.createElement('a')
    link.href = '/reload'
    link.setAttribute('data-pywire-reload', 'true')
    document.body.appendChild(link)

    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    const preventDefaultSpy = vi.spyOn(event, 'preventDefault')
    const navigateToSpy = vi.spyOn(app, 'navigateTo')

    link.dispatchEvent(event)

    expect(preventDefaultSpy).not.toHaveBeenCalled()
    expect(navigateToSpy).not.toHaveBeenCalled()
  })
})
