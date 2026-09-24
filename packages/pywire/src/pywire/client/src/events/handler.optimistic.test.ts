import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import { UnifiedEventHandler } from './handler'
import { PyWireApp } from '../core/app'
import { clearPending, revertPending } from './pending'

// Optimistic prediction is presentation-only and applied synchronously on
// dispatch. `data-pw-pending` doubles as the double-submit guard and is stripped
// by the next update (success → morph reconciles classes) or reverted on error.
describe('UnifiedEventHandler — optimistic prediction', () => {
  const appMock = {
    sendEvent: vi.fn(),
    getConfig: vi.fn().mockReturnValue({ debug: false }),
  }

  // init() attaches delegated document listeners that are never removed, so we
  // build ONE handler for the suite. Per-test handlers would stack listeners
  // whose stale predictions trip the shared `data-pw-pending` guard. In
  // production there is exactly one handler, so this matches reality.
  beforeAll(() => {
    const handler = new UnifiedEventHandler(appMock as unknown as PyWireApp)
    handler.init()
  })

  beforeEach(() => {
    document.body.innerHTML = ''
    clearPending() // reset module-level prediction tracking between tests
    appMock.sendEvent.mockClear()
  })

  function makeButton(): HTMLButtonElement {
    document.body.innerHTML =
      '<button id="btn" data-on-click="doIt" ' +
      'data-modifiers-click="optimistic optimistic-class-done">Go</button>'
    return document.getElementById('btn') as HTMLButtonElement
  }

  it('applies prediction synchronously on dispatch (same tick, before fetch resolves)', () => {
    const btn = makeButton()
    btn.click()

    expect(btn.hasAttribute('data-pw-pending')).toBe(true)
    expect(btn.classList.contains('done')).toBe(true)
    expect(btn.disabled).toBe(true)
    expect(btn.hasAttribute('data-pw-pending-disabled')).toBe(true)
    expect(appMock.sendEvent).toHaveBeenCalledTimes(1)
  })

  it('guards against double-submit while pending', () => {
    const btn = makeButton()
    btn.click()
    expect(appMock.sendEvent).toHaveBeenCalledTimes(1)

    // Second click while data-pw-pending is present → not sent. Dispatch directly
    // so we exercise the handler guard, not the browser's disabled-click suppression.
    btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    expect(appMock.sendEvent).toHaveBeenCalledTimes(1)
  })

  it('clears markers and re-enables the control on an update message', () => {
    const btn = makeButton()
    btn.click()
    expect(btn.disabled).toBe(true)

    clearPending() // what app.ts does on {type:'update'}

    expect(btn.hasAttribute('data-pw-pending')).toBe(false)
    expect(btn.hasAttribute('data-pw-pending-disabled')).toBe(false)
    expect(btn.disabled).toBe(false)
    // Success path: the morph is the reconciler, so the class is NOT force-removed here.
    expect(btn.classList.contains('done')).toBe(true)
  })

  it('clears markers AND removes predicted classes on an error message', () => {
    const btn = makeButton()
    btn.click()
    expect(btn.classList.contains('done')).toBe(true)
    expect(btn.disabled).toBe(true)

    revertPending() // what app.ts does on {type:'error'}

    expect(btn.hasAttribute('data-pw-pending')).toBe(false)
    expect(btn.hasAttribute('data-pw-pending-disabled')).toBe(false)
    expect(btn.disabled).toBe(false)
    expect(btn.classList.contains('done')).toBe(false)
  })

  it('releases the double-submit guard after an update', () => {
    const btn = makeButton()
    btn.click()
    clearPending()

    btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    expect(appMock.sendEvent).toHaveBeenCalledTimes(2)
  })

  it('releases the double-submit guard after an error', () => {
    const btn = makeButton()
    btn.click()
    revertPending()

    btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    expect(appMock.sendEvent).toHaveBeenCalledTimes(2)
  })
})
