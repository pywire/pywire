import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { UnifiedEventHandler } from './handler'
import { PyWireApp } from '../core/app'

describe('UnifiedEventHandler', () => {
  let appMock: {
    sendEvent: ReturnType<typeof vi.fn>
    getConfig: ReturnType<typeof vi.fn>
  }
  let handler: UnifiedEventHandler

  beforeEach(() => {
    document.body.innerHTML = ''
    appMock = {
      sendEvent: vi.fn(),
      getConfig: vi.fn().mockReturnValue({ debug: false }),
    }
    handler = new UnifiedEventHandler(appMock as unknown as PyWireApp)
  })

  it('should register listeners on init', () => {
    const addEventListenerSpy = vi.spyOn(document, 'addEventListener')
    handler.init()
    // Check for some common events
    expect(addEventListenerSpy).toHaveBeenCalledWith('click', expect.any(Function), undefined)
    expect(addEventListenerSpy).toHaveBeenCalledWith('submit', expect.any(Function), undefined)
    expect(addEventListenerSpy).toHaveBeenCalledWith('input', expect.any(Function), undefined)
    expect(addEventListenerSpy).toHaveBeenCalledWith('change', expect.any(Function), undefined)
  })

  it('should register specific listeners if present in DOM', () => {
    document.body.innerHTML = '<input data-on-focus="handleFocus">'
    const addEventListenerSpy = vi.spyOn(document, 'addEventListener')
    handler.init()
    expect(addEventListenerSpy).toHaveBeenCalledWith('focus', expect.any(Function), {
      capture: true,
    })
  })

  it('should handle basic click events', async () => {
    document.body.innerHTML = '<button id="btn" data-on-click="handleClick">Click Me</button>'
    const btn = document.getElementById('btn')!

    handler.init()
    btn.click()

    expect(appMock.sendEvent).toHaveBeenCalledWith(
      'handleClick',
      expect.objectContaining({
        type: 'click',
        id: 'btn',
      })
    )
  })

  it('should support .prevent modifier', () => {
    document.body.innerHTML =
      '<a href="#" id="link" data-on-click="nav" data-modifiers-click="prevent">Link</a>'
    const link = document.getElementById('link')!
    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    const preventDefaultSpy = vi.spyOn(event, 'preventDefault')

    handler.init()
    link.dispatchEvent(event)

    expect(preventDefaultSpy).toHaveBeenCalled()
    expect(appMock.sendEvent).toHaveBeenCalled()
  })

  it('should support .stop modifier', () => {
    document.body.innerHTML =
      '<div id="parent"><button id="child" data-on-click="hit" data-modifiers-click="stop"></button></div>'
    const child = document.getElementById('child')!
    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    const stopPropagationSpy = vi.spyOn(event, 'stopPropagation')

    handler.init()
    child.dispatchEvent(event)

    expect(stopPropagationSpy).toHaveBeenCalled()
  })

  it('should support .self modifier', () => {
    document.body.innerHTML = `
            <div id="outer" data-on-click="outerHit" data-modifiers-click="self">
                <button id="inner">Inner</button>
            </div>
        `
    const outer = document.getElementById('outer')!
    const inner = document.getElementById('inner')!

    handler.init()

    // Clicking inner should NOT trigger outer because of .self
    inner.click()
    expect(appMock.sendEvent).not.toHaveBeenCalledWith('outerHit', expect.anything())

    // Clicking outer should trigger
    outer.click()
    expect(appMock.sendEvent).toHaveBeenCalledWith('outerHit', expect.anything())
  })

  it('should support key modifiers like .enter', () => {
    document.body.innerHTML =
      '<input id="input" data-on-keyup="submit" data-modifiers-keyup="enter">'
    const input = document.getElementById('input')!

    handler.init()

    // Non-enter key should not trigger
    input.dispatchEvent(new KeyboardEvent('keyup', { key: 'a', bubbles: true }))
    expect(appMock.sendEvent).not.toHaveBeenCalled()

    // Enter key should trigger
    input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }))
    expect(appMock.sendEvent).toHaveBeenCalledWith(
      'submit',
      expect.objectContaining({
        type: 'keyup',
        key: 'Enter',
      })
    )
  })

  it('should handle .debounce modifier', async () => {
    vi.useFakeTimers()
    document.body.innerHTML =
      '<input id="input" data-on-input="search" data-modifiers-input="debounce">'
    const input = document.getElementById('input')!

    handler.init()

    // First input
    input.dispatchEvent(new Event('input', { bubbles: true }))
    expect(appMock.sendEvent).not.toHaveBeenCalled()

    // Second input quickly
    input.dispatchEvent(new Event('input', { bubbles: true }))

    // Wait for debounce (default 250ms)
    vi.advanceTimersByTime(300)

    expect(appMock.sendEvent).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it('sends every selected value of a multiple select', () => {
    document.body.innerHTML = `<select id="s" multiple data-on-change="pick">
        <option value="a" selected>A</option><option value="b">B</option>
        <option value="c" selected>C</option></select>`
    handler.init()
    document.getElementById('s')!.dispatchEvent(new Event('change', { bubbles: true }))
    expect(appMock.sendEvent).toHaveBeenCalledWith(
      'pick',
      expect.objectContaining({ values: ['a', 'c'] })
    )
  })

  it('should extract input value', () => {
    document.body.innerHTML = '<input id="input" value="hello" data-on-change="save">'
    const input = document.getElementById('input')!

    handler.init()
    input.dispatchEvent(new Event('change', { bubbles: true }))

    expect(appMock.sendEvent).toHaveBeenCalledWith(
      'save',
      expect.objectContaining({
        value: 'hello',
      })
    )
  })

  it('should handle form submit and extract data', async () => {
    document.body.innerHTML = `
            <form id="form" data-on-submit="send">
                <input name="user" value="alice">
                <input name="pass" value="secret">
            </form>
        `
    const form = document.getElementById('form')!

    handler.init()
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))

    expect(appMock.sendEvent).toHaveBeenCalledWith(
      'send',
      expect.objectContaining({
        type: 'submit',
        formData: {
          user: 'alice',
          pass: 'secret',
        },
      })
    )
  })

  it('clears stale custom validity on file change', () => {
    document.body.innerHTML = `
            <form id="form" data-on-submit="send">
                <input id="avatar" type="file" name="avatar" data-on-change="changed">
            </form>
        `
    const avatar = document.getElementById('avatar') as HTMLInputElement
    const goodFile = new File(['x'], 'avatar_ok.png', { type: 'image/png' })
    Object.defineProperty(avatar, 'files', { value: [goodFile], configurable: true })
    avatar.setCustomValidity('Filename is not allowed')

    handler.init()
    avatar.dispatchEvent(new Event('change', { bubbles: true }))

    expect(avatar.validationMessage).toBe('')
  })

  it('clears stale custom validity on file change without data-on-change handler', () => {
    document.body.innerHTML = `
            <form id="form" data-on-submit="send">
                <input id="avatar" type="file" name="avatar">
            </form>
        `
    const avatar = document.getElementById('avatar') as HTMLInputElement
    const goodFile = new File(['x'], 'avatar_ok.png', { type: 'image/png' })
    Object.defineProperty(avatar, 'files', { value: [goodFile], configurable: true })
    avatar.setCustomValidity('Filename is not allowed')

    handler.init()
    avatar.dispatchEvent(new Event('change', { bubbles: true }))

    expect(avatar.validationMessage).toBe('')
  })

  it('should handle .throttle modifier', async () => {
    vi.useFakeTimers()
    document.body.innerHTML =
      '<button id="btn" data-on-click="fire" data-modifiers-click="throttle"></button>'
    const btn = document.getElementById('btn')!

    handler.init()

    // First click - immediate
    btn.click()
    expect(appMock.sendEvent).toHaveBeenCalledTimes(1)

    // More clicks inside the window collapse into one trailing send
    btn.click()
    btn.click()
    expect(appMock.sendEvent).toHaveBeenCalledTimes(1)

    // Window ends (default 250ms): the last click arrives
    vi.advanceTimersByTime(300)
    expect(appMock.sendEvent).toHaveBeenCalledTimes(2)

    // Quiet window, then a click sends at once again
    vi.advanceTimersByTime(300)
    btn.click()
    expect(appMock.sendEvent).toHaveBeenCalledTimes(3)
    vi.useRealTimers()
  })

  describe('timing defaults', () => {
    beforeEach(() => vi.useFakeTimers())
    afterEach(() => vi.useRealTimers())

    const fire = (el: Element, type: string): void => {
      el.dispatchEvent(new Event(type, { bubbles: true }))
    }

    it('debounces @input on text inputs by default', () => {
      document.body.innerHTML = '<input id="q" data-on-input="search">'
      handler.init()
      const q = document.getElementById('q')!
      fire(q, 'input')
      fire(q, 'input')
      expect(appMock.sendEvent).not.toHaveBeenCalled()
      vi.advanceTimersByTime(260)
      expect(appMock.sendEvent).toHaveBeenCalledTimes(1)
    })

    it('sends @input from a checkbox at once', () => {
      document.body.innerHTML = '<input id="c" type="checkbox" data-on-input="tick">'
      handler.init()
      fire(document.getElementById('c')!, 'input')
      expect(appMock.sendEvent).toHaveBeenCalledTimes(1)
    })

    it('.immediate opts out of the default', () => {
      document.body.innerHTML =
        '<input id="q" data-on-input="search" data-modifiers-input="immediate">'
      handler.init()
      fire(document.getElementById('q')!, 'input')
      expect(appMock.sendEvent).toHaveBeenCalledTimes(1)
    })

    it('flushes a pending debounced event before a click', () => {
      document.body.innerHTML =
        '<input id="q" data-on-input="search"><button id="b" data-on-click="save"></button>'
      handler.init()
      fire(document.getElementById('q')!, 'input')
      ;(document.getElementById('b') as HTMLButtonElement).click()
      expect(appMock.sendEvent.mock.calls.map((c) => c[0])).toEqual(['search', 'save'])
      vi.advanceTimersByTime(500)
      expect(appMock.sendEvent).toHaveBeenCalledTimes(2)
    })

    it('flushes waiting events in the order they happened', () => {
      document.body.innerHTML =
        '<div id="s" data-on-scroll="moved"></div><input id="q" data-on-input="search">' +
        '<button id="b" data-on-click="save"></button>'
      handler.init()
      const s = document.getElementById('s')!
      fire(s, 'scroll') // sent at once, opens the window
      fire(s, 'scroll') // trailing, waiting
      fire(document.getElementById('q')!, 'input') // debounced, waiting
      ;(document.getElementById('b') as HTMLButtonElement).click()
      expect(appMock.sendEvent.mock.calls.map((c) => c[0])).toEqual([
        'moved',
        'moved',
        'search',
        'save',
      ])
    })

    it('waits 250ms for a configured timing without a duration', () => {
      appMock.getConfig.mockReturnValue({ eventDefaults: { keyup: 'debounce' } })
      document.body.innerHTML = '<input id="q" data-on-keyup="typed">'
      handler.init()
      fire(document.getElementById('q')!, 'keyup')
      vi.advanceTimersByTime(200)
      expect(appMock.sendEvent).not.toHaveBeenCalled()
      vi.advanceTimersByTime(100)
      expect(appMock.sendEvent).toHaveBeenCalledTimes(1)
    })

    it('throttles scroll with a trailing send', () => {
      document.body.innerHTML = '<div id="s" data-on-scroll="moved"></div>'
      handler.init()
      const s = document.getElementById('s')!
      fire(s, 'scroll')
      fire(s, 'scroll')
      fire(s, 'scroll')
      expect(appMock.sendEvent).toHaveBeenCalledTimes(1)
      vi.advanceTimersByTime(110)
      expect(appMock.sendEvent).toHaveBeenCalledTimes(2)
    })

    it('uses PyWire(event_defaults=...) from the page config', () => {
      appMock.getConfig.mockReturnValue({ eventDefaults: { input: 'debounce.500ms' } })
      document.body.innerHTML = '<input id="q" data-on-input="search">'
      handler.init()
      fire(document.getElementById('q')!, 'input')
      vi.advanceTimersByTime(300)
      expect(appMock.sendEvent).not.toHaveBeenCalled()
      vi.advanceTimersByTime(250)
      expect(appMock.sendEvent).toHaveBeenCalledTimes(1)
    })
  })

  it('should support system modifiers like .shift.ctrl', () => {
    document.body.innerHTML =
      '<button id="btn" data-on-click="hit" data-modifiers-click="shift ctrl"></button>'
    const btn = document.getElementById('btn')!
    handler.init()

    // Click without modifiers - no trigger
    btn.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(appMock.sendEvent).not.toHaveBeenCalled()

    // Click with only shift - no trigger
    btn.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }))
    expect(appMock.sendEvent).not.toHaveBeenCalled()

    // Click with BOTH shift and ctrl - trigger
    btn.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true, ctrlKey: true }))
    expect(appMock.sendEvent).toHaveBeenCalled()
  })

  it('should support .window modifier', () => {
    document.body.innerHTML = '<div data-on-click="winHit" data-modifiers-click="window"></div>'
    handler.init()

    // Click anywhere (document.body)
    document.body.click()
    expect(appMock.sendEvent).toHaveBeenCalledWith('winHit', expect.anything())
  })

  it('should support .outside modifier', () => {
    document.body.innerHTML = `
            <div id="modal" data-on-click="close" data-modifiers-click="outside">
                <button id="inside">Inside</button>
            </div>
            <button id="outside">Outside</button>
        `
    const inside = document.getElementById('inside')!
    const outside = document.getElementById('outside')!
    handler.init()

    // Clicking inside should NOT trigger
    inside.click()
    expect(appMock.sendEvent).not.toHaveBeenCalled()

    // Clicking outside should trigger
    outside.click()
    expect(appMock.sendEvent).toHaveBeenCalledWith('close', expect.anything())
  })

  it('should handle dynamic delegation', () => {
    handler.init()

    // Add element AFTER init
    const div = document.createElement('div')
    div.innerHTML = '<button id="dyn" data-on-click="dynamic">Dyn</button>'
    document.body.appendChild(div)

    const btn = document.getElementById('dyn')!
    btn.click()

    expect(appMock.sendEvent).toHaveBeenCalledWith('dynamic', expect.anything())
  })

  it('should handle custom events', () => {
    document.body.innerHTML = '<div id="custom-el" data-on-my-event="handleCustom"></div>'
    const el = document.getElementById('custom-el')!

    // Initialize handler to scan for my-event
    handler.init()

    el.dispatchEvent(new CustomEvent('my-event', { bubbles: true, detail: { some: 'data' } }))

    expect(appMock.sendEvent).toHaveBeenCalledWith(
      'handleCustom',
      expect.objectContaining({
        type: 'my-event',
      })
    )
  })

  it('should support multiple handlers via JSON', () => {
    document.body.innerHTML = `
            <button id="multi" 
                data-on-click='[{"handler": "foo", "modifiers": ["stop"]}, {"handler": "bar", "modifiers": ["prevent"]}]'
            ></button>
        `
    const btn = document.getElementById('multi')!
    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    const stopPropagationSpy = vi.spyOn(event, 'stopPropagation')
    const preventDefaultSpy = vi.spyOn(event, 'preventDefault')

    handler.init()
    btn.dispatchEvent(event)

    expect(appMock.sendEvent).toHaveBeenCalledWith('foo', expect.anything())
    expect(appMock.sendEvent).toHaveBeenCalledWith('bar', expect.anything())
    expect(stopPropagationSpy).toHaveBeenCalled()
    expect(preventDefaultSpy).toHaveBeenCalled()
  })

  it('should handle explicit arguments in JSON handlers', () => {
    document.body.innerHTML = `
            <button id="args" 
                data-on-click='[{"handler": "save", "modifiers": [], "args": [1, "test"]}]'
            ></button>
        `
    const btn = document.getElementById('args')!

    handler.init()
    btn.click()

    expect(appMock.sendEvent).toHaveBeenCalledWith(
      'save',
      expect.objectContaining({
        args: {
          arg0: 1,
          arg1: 'test',
        },
      })
    )
  })

  it('should fallback to e.code for key modifiers', () => {
    document.body.innerHTML = '<input id="input" data-on-keyup="hit" data-modifiers-keyup="h">'
    const input = document.getElementById('input')!

    handler.init()

    // Simulate Alt+H which might produce '˙' but has code 'KeyH'
    input.dispatchEvent(new KeyboardEvent('keyup', { key: '˙', code: 'KeyH', bubbles: true }))

    expect(appMock.sendEvent).toHaveBeenCalledWith('hit', expect.anything())
  })
})
