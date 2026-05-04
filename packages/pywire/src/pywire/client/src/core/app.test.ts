import { describe, it, expect, vi, beforeEach } from 'vitest'
import { PyWireApp } from './app'

// Mock dependencies
vi.mock('./transport-manager', () => {
  return {
    TransportManager: vi.fn().mockImplementation(function () {
      return {
        onMessage: vi.fn(),
        onStatusChange: vi.fn(),
        onGiveUp: vi.fn(),
        setMaxReconnectAttempts: vi.fn(),
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
    // Remove any leftover SPA metadata from previous tests
    document.getElementById('_pywire_spa_meta')?.remove()
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

  it('should NOT intercept link clicks with data-pw-reload', async () => {
    // Setup metadata (enable pjax with matching route to ensure it would otherwise intercept)
    const meta = document.createElement('script')
    meta.id = '_pywire_spa_meta'
    meta.textContent = JSON.stringify({ enable_pjax: true, all_paths: ['/reload'] })
    document.head.appendChild(meta)

    await app.init()

    const link = document.createElement('a')
    link.href = '/reload'
    link.setAttribute('data-pw-reload', 'true')
    document.body.appendChild(link)

    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    const preventDefaultSpy = vi.spyOn(event, 'preventDefault')
    const navigateToSpy = vi.spyOn(app, 'navigateTo')

    link.dispatchEvent(event)

    expect(preventDefaultSpy).not.toHaveBeenCalled()
    expect(navigateToSpy).not.toHaveBeenCalled()
  })

  it('should NOT intercept clicks on static asset links', async () => {
    const meta = document.createElement('script')
    meta.id = '_pywire_spa_meta'
    meta.textContent = JSON.stringify({
      enable_pjax: true,
      all_paths: ['/'],
      static_path: '/static',
    })
    document.head.appendChild(meta)

    await app.init()

    const link = document.createElement('a')
    link.href = '/static/file.txt'
    document.body.appendChild(link)

    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    const preventDefaultSpy = vi.spyOn(event, 'preventDefault')
    const navigateToSpy = vi.spyOn(app, 'navigateTo')

    link.dispatchEvent(event)

    expect(preventDefaultSpy).not.toHaveBeenCalled()
    expect(navigateToSpy).not.toHaveBeenCalled()
  })

  it('should NOT intercept clicks on static links with custom static_path', async () => {
    const meta = document.createElement('script')
    meta.id = '_pywire_spa_meta'
    meta.textContent = JSON.stringify({
      enable_pjax: true,
      all_paths: ['/'],
      static_path: '/assets',
    })
    document.head.appendChild(meta)

    await app.init()

    const link = document.createElement('a')
    link.href = '/assets/logo.png'
    document.body.appendChild(link)

    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    const preventDefaultSpy = vi.spyOn(event, 'preventDefault')
    const navigateToSpy = vi.spyOn(app, 'navigateTo')

    link.dispatchEvent(event)

    expect(preventDefaultSpy).not.toHaveBeenCalled()
    expect(navigateToSpy).not.toHaveBeenCalled()
  })

  it('should NOT intercept non-wire links when pjax enabled', async () => {
    const meta = document.createElement('script')
    meta.id = '_pywire_spa_meta'
    meta.textContent = JSON.stringify({ enable_pjax: true, all_paths: ['/', '/about'] })
    document.head.appendChild(meta)

    await app.init()

    const link = document.createElement('a')
    link.href = '/login'
    document.body.appendChild(link)

    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    const preventDefaultSpy = vi.spyOn(event, 'preventDefault')
    const navigateToSpy = vi.spyOn(app, 'navigateTo')

    link.dispatchEvent(event)

    expect(preventDefaultSpy).not.toHaveBeenCalled()
    expect(navigateToSpy).not.toHaveBeenCalled()
  })

  it('should intercept wire links when pjax enabled', async () => {
    const meta = document.createElement('script')
    meta.id = '_pywire_spa_meta'
    meta.textContent = JSON.stringify({ enable_pjax: true, all_paths: ['/', '/about'] })
    document.head.appendChild(meta)

    await app.init()

    const link = document.createElement('a')
    link.href = '/about'
    document.body.appendChild(link)

    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    const preventDefaultSpy = vi.spyOn(event, 'preventDefault')
    const navigateToSpy = vi.spyOn(app, 'navigateTo').mockImplementation(() => {})

    link.dispatchEvent(event)

    expect(preventDefaultSpy).toHaveBeenCalled()
    expect(navigateToSpy).toHaveBeenCalledWith('/about')
  })

  it('should intercept parameterized wire paths when pjax enabled', async () => {
    const meta = document.createElement('script')
    meta.id = '_pywire_spa_meta'
    meta.textContent = JSON.stringify({ enable_pjax: true, all_paths: ['/users/:id'] })
    document.head.appendChild(meta)

    await app.init()

    const link = document.createElement('a')
    link.href = '/users/42'
    document.body.appendChild(link)

    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    const preventDefaultSpy = vi.spyOn(event, 'preventDefault')
    const navigateToSpy = vi.spyOn(app, 'navigateTo').mockImplementation(() => {})

    link.dispatchEvent(event)

    expect(preventDefaultSpy).toHaveBeenCalled()
    expect(navigateToSpy).toHaveBeenCalledWith('/users/42')
  })
})
