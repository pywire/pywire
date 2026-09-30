import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
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

  describe('events and SPA navigation', () => {
    const sent = () =>
      (
        app as unknown as { transport: { send: ReturnType<typeof vi.fn> } }
      ).transport.send.mock.calls.map(
        (c) => c[0] as { type: string; handler?: string; path?: string }
      )

    beforeEach(async () => {
      vi.useFakeTimers()
      history.replaceState({}, '', '/a')
      app = new PyWireApp({ autoInit: false })
      document.body.innerHTML =
        '<input id="q" data-on-input="act" data-modifiers-input="debounce.300ms">'
      await app.init()
      ;(app as unknown as { isConnected: boolean }).isConnected = true
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('sends pending input to the page it was typed on, then nothing until the next page', () => {
      document.getElementById('q')!.dispatchEvent(new Event('input', { bubbles: true }))
      app.navigateTo('/b')
      expect(sent().map((m) => [m.type, m.path ?? m.handler])).toEqual([
        ['event', '/a'],
        ['relocate', '/b'],
      ])

      // The old DOM is still showing: its events are dropped.
      app.sendEvent('act', {} as never)
      vi.advanceTimersByTime(1000)
      expect(sent()).toHaveLength(2)
    })

    it('stamps events with the page that is shown once it arrives', async () => {
      app.navigateTo('/b')
      await (app as unknown as { handleMessage(m: unknown): Promise<void> }).handleMessage({
        type: 'update',
        html: '<p>b</p>',
      })
      app.sendEvent('act', {} as never)
      expect(sent().slice(-1)[0]).toMatchObject({ type: 'event', path: '/b' })
    })

    it('does not take an event reply for the new page', async () => {
      app.navigateTo('/b')
      const handle = (m: unknown) =>
        (app as unknown as { handleMessage(m: unknown): Promise<void> }).handleMessage(m)
      await handle({ type: 'update', regions: [], ack: 1 })
      app.sendEvent('act', {} as never)
      expect(sent().slice(-1)[0]).toMatchObject({ type: 'relocate' })
    })
  })

  it.each([
    ['/demo', true],
    ['/demo/', true],
    ['/demo/about', true],
    ['/', false],
    ['/other', false],
  ])('under a URL prefix, link to %s is intercepted: %s', async (href, intercepted) => {
    const meta = document.createElement('script')
    meta.id = '_pywire_spa_meta'
    meta.textContent = JSON.stringify({
      enable_pjax: true,
      mount_path: '/demo',
      all_paths: ['/demo/', '/demo/about'],
    })
    document.head.appendChild(meta)

    await app.init()

    const link = document.createElement('a')
    link.href = href
    document.body.appendChild(link)

    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    const navigateToSpy = vi.spyOn(app, 'navigateTo').mockImplementation(() => {})

    link.dispatchEvent(event)

    expect(navigateToSpy).toHaveBeenCalledTimes(intercepted ? 1 : 0)
  })
})
