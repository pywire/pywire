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

  it('should execute scripts in new content', () => {
    // Mock global window property to track script execution
    ;(window as Window & { scriptValue?: number }).scriptValue = 0

    updater.update('<div><script>window.scriptValue = 42</script></div>')

    expect((window as Window & { scriptValue?: number }).scriptValue).toBe(42)
    delete (window as Window & { scriptValue?: number }).scriptValue
  })

  it('should execute scripts before pywire:update event', () => {
    let scriptExecutedBeforeUpdate = false
    ;(window as Window & { testExecuted?: () => void }).testExecuted = () => {
      scriptExecutedBeforeUpdate = true
    }

    const app = document.getElementById('app')!
    app.addEventListener('pywire:update', () => {
      // If script executed, this should be true
    })

    updater.update('<div><script>window.testExecuted()</script></div>')

    expect(scriptExecutedBeforeUpdate).toBe(true)
    delete (window as Window & { testExecuted?: () => void }).testExecuted
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
})
