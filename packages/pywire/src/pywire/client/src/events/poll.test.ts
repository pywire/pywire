import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { UnifiedEventHandler } from './handler'
import { clearPollInFlight } from './poll'
import { PyWireApp } from '../core/app'

// @poll is a kernel timer: mounted poll elements dispatch their handler on an
// interval through the same app.sendEvent path a click uses, and the timer
// dies with the element (unmount / region replacement / navigation).
describe('UnifiedEventHandler — @poll scheduling', () => {
  let appMock: { sendEvent: ReturnType<typeof vi.fn>; getConfig: ReturnType<typeof vi.fn> }
  let handler: UnifiedEventHandler

  beforeEach(() => {
    document.body.innerHTML = ''
    vi.useFakeTimers()
    appMock = {
      sendEvent: vi.fn(),
      getConfig: vi.fn().mockReturnValue({ debug: false }),
    }
    handler = new UnifiedEventHandler(appMock as unknown as PyWireApp)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  function mountPoll(interval?: number): HTMLElement {
    const every = interval !== undefined ? ` data-pw-poll-every="${interval}"` : ''
    document.body.innerHTML = `<button id="poll" data-pw-poll="tick"${every}>Poll</button>`
    return document.getElementById('poll') as HTMLElement
  }

  it('dispatches on the default 1000ms interval', () => {
    mountPoll()
    handler.init()

    vi.advanceTimersByTime(999)
    expect(appMock.sendEvent).not.toHaveBeenCalled()

    vi.advanceTimersByTime(1)
    expect(appMock.sendEvent).toHaveBeenCalledTimes(1)
    expect(appMock.sendEvent).toHaveBeenCalledWith(
      'tick',
      expect.objectContaining({ type: 'poll', id: 'poll' })
    )
  })

  it('dispatches on the configured interval', () => {
    mountPoll(400)
    handler.init()

    vi.advanceTimersByTime(399)
    expect(appMock.sendEvent).not.toHaveBeenCalled()

    vi.advanceTimersByTime(1)
    expect(appMock.sendEvent).toHaveBeenCalledTimes(1)
  })

  it('stops dispatching after the element unmounts', () => {
    const el = mountPoll()
    handler.init()
    vi.advanceTimersByTime(1000)
    expect(appMock.sendEvent).toHaveBeenCalledTimes(1)

    el.remove()
    handler.refreshListeners() // the morph/region-replacement hook
    vi.advanceTimersByTime(5000)
    expect(appMock.sendEvent).toHaveBeenCalledTimes(1)
  })

  it('does not dispatch for a poll element removed without a refresh (disconnected guard)', () => {
    const el = mountPoll()
    handler.init()
    vi.advanceTimersByTime(1000)
    expect(appMock.sendEvent).toHaveBeenCalledTimes(1)

    el.remove() // no refreshListeners yet — the tick must still no-op
    expect(el.isConnected).toBe(false)
    vi.advanceTimersByTime(1000)
    expect(appMock.sendEvent).toHaveBeenCalledTimes(1)
  })

  it('skips a tick while a prior dispatch is in flight', () => {
    mountPoll(400)
    handler.init()

    vi.advanceTimersByTime(400)
    expect(appMock.sendEvent).toHaveBeenCalledTimes(1)

    // No response yet → the next tick is skipped (overlap guard).
    vi.advanceTimersByTime(400)
    expect(appMock.sendEvent).toHaveBeenCalledTimes(1)

    // Response arrives (even an empty update) → in-flight cleared.
    clearPollInFlight()
    vi.advanceTimersByTime(400)
    expect(appMock.sendEvent).toHaveBeenCalledTimes(2)
  })

  it('keeps independent poll elements on their own intervals', () => {
    document.body.innerHTML =
      '<button id="a" data-pw-poll="tickA" data-pw-poll-every="400">A</button>' +
      '<button id="b" data-pw-poll="tickB">B</button>'
    handler.init()

    vi.advanceTimersByTime(400)
    expect(appMock.sendEvent).toHaveBeenCalledWith('tickA', expect.anything())
    expect(appMock.sendEvent).not.toHaveBeenCalledWith('tickB', expect.anything())

    vi.advanceTimersByTime(600)
    expect(appMock.sendEvent).toHaveBeenCalledWith('tickB', expect.anything())
  })
})
