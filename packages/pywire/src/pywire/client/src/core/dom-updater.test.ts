import { describe, it, expect, vi, beforeEach } from 'vitest'
import { DOMUpdater } from './dom-updater'
import morphdom from 'morphdom'

vi.mock('morphdom', () => ({
  default: vi.fn((_from, _to, _options) => {
    // Basic simulation of morphdom: just replace content if no options,
    // or call hooks if provided (we only care about onBeforeElUpdated)
    return
  }),
}))

describe('DOMUpdater', () => {
  let updater: DOMUpdater

  beforeEach(() => {
    vi.clearAllMocks()
    updater = new DOMUpdater()
    document.documentElement.innerHTML = '<body><div id="app"></div></body>'
  })

  it('should call morphdom with custom options', () => {
    updater.update('<html><body><div id="app">New</div></body></html>')
    expect(morphdom).toHaveBeenCalledTimes(1)
    const [target, content, options] = vi.mocked(morphdom).mock.calls[0]

    expect(target).toBeInstanceOf(Node)
    expect(content).toBeInstanceOf(Node)
    expect((content as Element).textContent).toContain('New')
    expect(options).toEqual(
      expect.objectContaining({
        onBeforeElUpdated: expect.any(Function),
      })
    )
  })

  it('should preserve input value if focused and similar', () => {
    const morphdomMock = vi.mocked(morphdom)
    updater.update('<html><body><input id="test" value="server"></body></html>')

    // Get the onBeforeElUpdated hook
    const options = morphdomMock.mock.calls[0][2]
    const onBeforeElUpdated = options?.onBeforeElUpdated

    if (!onBeforeElUpdated) throw new Error('Hook not found')

    const fromEl = document.createElement('input')
    fromEl.value = 'server-ahead'
    vi.spyOn(document, 'activeElement', 'get').mockReturnValue(fromEl)

    const toEl = document.createElement('input')
    toEl.setAttribute('value', 'server')

    const result = onBeforeElUpdated(fromEl, toEl)

    expect(result).toBe(true)
    expect(toEl.value).toBe('server-ahead')
  })

  it('should NOT preserve input value if completely different', () => {
    const morphdomMock = vi.mocked(morphdom)
    updater.update('<html><body><input id="test" value="server"></body></html>')

    const options = morphdomMock.mock.calls[0][2]
    const onBeforeElUpdated = options?.onBeforeElUpdated

    if (!onBeforeElUpdated) throw new Error('Hook not found')

    const fromEl = document.createElement('input')
    fromEl.value = 'user-typed-something-else'
    vi.spyOn(document, 'activeElement', 'get').mockReturnValue(fromEl)

    const toEl = document.createElement('input')
    toEl.setAttribute('value', 'server-new')
    toEl.value = 'server-new'

    onBeforeElUpdated(fromEl, toEl)

    // Should NOT have overwritten toEl.value with fromEl.value because they don't start with each other
    expect(toEl.value).toBe('server-new')
  })

  it('should preserve file input node and sync attributes', () => {
    const morphdomMock = vi.mocked(morphdom)
    updater.update('<html><body><input id="avatar" type="file"></body></html>')

    const options = morphdomMock.mock.calls[0][2]
    const onBeforeElUpdated = options?.onBeforeElUpdated
    if (!onBeforeElUpdated) throw new Error('Hook not found')

    const fromEl = document.createElement('input')
    fromEl.type = 'file'
    fromEl.name = 'avatar'
    const toEl = document.createElement('input')
    toEl.type = 'file'
    toEl.name = 'avatar'
    toEl.disabled = true
    toEl.setAttribute('accept', '.png')

    const result = onBeforeElUpdated(fromEl, toEl)

    expect(result).toBe(false)
    expect(fromEl.disabled).toBe(true)
    expect(fromEl.getAttribute('accept')).toBe('.png')
  })

  it('should not restore file input values during focus restore', () => {
    const fileInput = document.createElement('input')
    fileInput.type = 'file'
    fileInput.id = 'avatar'
    document.body.appendChild(fileInput)
    vi.spyOn(document, 'activeElement', 'get').mockReturnValue(fileInput)

    // Trigger update and make sure restoreFocusState path does not try to set value for file input.
    expect(() =>
      updater.update('<html><body><input id="avatar" type="file"></body></html>')
    ).not.toThrow()
  })

  it('should skip children update if data-pw-permanent is present', () => {
    const morphdomMock = vi.mocked(morphdom)
    updater.update(
      '<html><body><div id="perm" data-pw-permanent="true"><span>New Content</span></div></body></html>'
    )

    const options = morphdomMock.mock.calls[0][2]
    const onBeforeElChildrenUpdated = options?.onBeforeElChildrenUpdated

    if (!onBeforeElChildrenUpdated) throw new Error('Hook not found')

    const fromEl = document.createElement('div')
    fromEl.setAttribute('data-pw-permanent', 'true')
    const toEl = document.createElement('div')

    const result = onBeforeElChildrenUpdated(fromEl, toEl)

    expect(result).toBe(false)
  })

  it('should dispatch lifecycle events', () => {
    const el = document.getElementById('app')!
    const preSpy = vi.fn()
    const updateSpy = vi.fn()
    const postSpy = vi.fn()

    document.documentElement.addEventListener('pywire:preupdate', preSpy)
    el.addEventListener('pywire:update', updateSpy)
    document.documentElement.addEventListener('pywire:postupdate', postSpy)

    // Using vi.mocked(morphdom) to trigger the onElUpdated hook manually since mock is simple
    const morphdomMock = vi.mocked(morphdom)

    updater.update('<html><body><div id="app">Updated</div></body></html>')

    // preupdate should be called before morphdom
    expect(preSpy).toHaveBeenCalled()

    // Simulate morphdom calling hooks
    const options = morphdomMock.mock.calls[0][2]
    const onElUpdated = options?.onElUpdated
    if (onElUpdated) {
      onElUpdated(el)
    }

    // update event should be dispatched during morphdom execution
    expect(updateSpy).toHaveBeenCalled()

    // postupdate should be called after morphdom
    expect(postSpy).toHaveBeenCalled()
  })

  it('should re-inject inline scripts via <script> appendChild (CSP-safe)', () => {
    // happy-dom does not actually run JS on appendChild, so we verify
    // the DOM behavior the production browser then runs. Real browsers
    // execute the appended <script> synchronously under the same
    // 'unsafe-inline' that allowed it on the initial page load — without
    // needing 'unsafe-eval' (which the previous indirect-eval approach
    // required).
    const appendSpy = vi
      .spyOn(document.head, 'appendChild')
      .mockImplementation((node) => node as Node)

    updater.update('<div><script>window.scriptValue = 42</script></div>')

    const injected = appendSpy.mock.calls.find(
      (call) =>
        call[0] instanceof HTMLScriptElement &&
        ((call[0] as HTMLScriptElement).textContent || '').includes('scriptValue')
    )?.[0] as HTMLScriptElement | undefined

    expect(injected).toBeDefined()
    expect(injected!.getAttribute('src')).toBeNull()
    appendSpy.mockRestore()
  })

  it('should NOT re-inject an identical inline script across SPA updates', () => {
    // An inline script with top-level `const`/`let`/`function` can't be
    // re-executed without a SyntaxError. Once a body has run, repeat
    // injections of the same body are skipped.
    const appendSpy = vi
      .spyOn(document.head, 'appendChild')
      .mockImplementation((node) => node as Node)

    const html = '<div><script>const tamperWired = true</script></div>'
    updater.update(html)
    updater.update(html)

    const injections = appendSpy.mock.calls.filter(
      (c) =>
        c[0] instanceof HTMLScriptElement &&
        ((c[0] as HTMLScriptElement).textContent || '').includes('tamperWired')
    )
    expect(injections.length).toBe(1)
    appendSpy.mockRestore()
  })

  it('should re-inject inline scripts before pywire:postupdate fires', () => {
    const order: string[] = []
    const appendSpy = vi
      .spyOn(document.head, 'appendChild')
      .mockImplementation((node) => {
        if (
          node instanceof HTMLScriptElement &&
          (node.textContent || '').includes('marker')
        ) {
          order.push('script-injected')
        }
        return node as Node
      })

    document.documentElement.addEventListener('pywire:postupdate', () => {
      order.push('postupdate')
    })

    updater.update('<div><script>/* marker */</script></div>')

    expect(order).toEqual(['script-injected', 'postupdate'])
    appendSpy.mockRestore()
  })

  it('should not re-execute scripts inside data-pw-permanent elements', () => {
    ;(window as Window & { permScriptRan?: boolean }).permScriptRan = false

    updater.update(
      '<div><div data-pw-permanent><script>window.permScriptRan = true</script></div></div>'
    )

    expect((window as Window & { permScriptRan?: boolean }).permScriptRan).toBe(false)
    delete (window as Window & { permScriptRan?: boolean }).permScriptRan
  })

  it('should skip duplicate external scripts already in head', () => {
    // Mock appendChild before adding the existing script so happy-dom doesn't
    // try to load the src in the test environment.
    const appendSpy = vi
      .spyOn(document.head, 'appendChild')
      .mockImplementation((node) => node as Node)

    // Simulate an existing script already in <head> via querySelector
    const querySpy = vi
      .spyOn(document.head, 'querySelector')
      .mockImplementation((selector: string) => {
        if (selector === 'script[src="already-loaded.js"]') {
          return document.createElement('script')
        }
        return null
      })

    updater.update('<div><script src="already-loaded.js"></script></div>')

    // appendChild should NOT have been called for the duplicate script
    const duplicateCall = appendSpy.mock.calls.find(
      (call) =>
        call[0] instanceof HTMLScriptElement &&
        (call[0] as HTMLScriptElement).getAttribute('src') === 'already-loaded.js'
    )

    expect(duplicateCall).toBeUndefined()
    appendSpy.mockRestore()
    querySpy.mockRestore()
  })

  it('should execute scripts with attributes', () => {
    const appendSpy = vi
      .spyOn(document.head, 'appendChild')
      .mockImplementation((node) => node as Node)

    updater.update('<div><script src="test.js" async></script></div>')

    const script = appendSpy.mock.calls.find(
      (call) =>
        call[0] instanceof HTMLScriptElement &&
        (call[0] as HTMLScriptElement).src.includes('test.js')
    )?.[0] as HTMLScriptElement

    expect(script).toBeDefined()
    expect(script.getAttribute('src')).toBe('test.js')
    expect(script.hasAttribute('async')).toBe(true)

    appendSpy.mockRestore()
  })

  it('should defer an inline script until a preceding non-async src loads', async () => {
    const order: string[] = []

    const appendSpy = vi.spyOn(document.head, 'appendChild').mockImplementation((node) => {
      const s = node as HTMLScriptElement
      if (s.tagName === 'SCRIPT' && s.getAttribute('src')) {
        order.push('src-appended')
        // Simulate async load — dispatch `load` on the microtask queue so the
        // subsequent inline script can be observed to wait.
        queueMicrotask(() => {
          order.push('src-loaded')
          s.dispatchEvent(new Event('load'))
        })
      } else if (
        s.tagName === 'SCRIPT' &&
        (s.textContent || '').includes('chartCtor')
      ) {
        order.push('inline-appended')
      }
      return node as Node
    })

    updater.update(
      '<div><script src="chart.js"></script><script>window.chartCtor()</script></div>'
    )

    // Flush microtasks so the whole chain runs: src-appended → load
    // handler resolves → chained inline gets appended.
    for (let i = 0; i < 5; i++) {
      await new Promise<void>((r) => queueMicrotask(r))
    }

    // The inline append must not happen until AFTER the src has loaded —
    // verifies the chain.then() ordering.
    expect(order).toEqual(['src-appended', 'src-loaded', 'inline-appended'])
    appendSpy.mockRestore()
  })
})
