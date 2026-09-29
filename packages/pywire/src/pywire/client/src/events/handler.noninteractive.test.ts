import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import { UnifiedEventHandler } from './handler'
import { PyWireApp } from '../core/app'
import { clearPending } from './pending'

// Spy on clearPending (delegating to the real impl) so the app-side test can
// assert httpFormSubmit flushes predictions after its full-document morph.
vi.mock('./pending', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./pending')>()
  return { ...actual, clearPending: vi.fn(actual.clearPending) }
})

// Mocked out for the real-PyWireApp httpFormSubmit test (same mocks as app.test.ts).
vi.mock('../core/transport-manager', () => {
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

vi.mock('../core/dom-updater', () => {
  return {
    DOMUpdater: vi.fn().mockImplementation(function () {
      return {
        update: vi.fn(),
        updateRegion: vi.fn(),
      }
    }),
  }
})

// Non-interactive (SSR) mode: `@submit.optimistic` must apply its prediction
// and double-submit guard before httpFormSubmit's async POST — the early-return
// path never reaches the interactive sendEvent code that used to do this.
describe('UnifiedEventHandler — optimistic on non-interactive submit', () => {
  const appMock = {
    isInteractive: false,
    httpFormSubmit: vi.fn().mockResolvedValue(undefined),
    sendEvent: vi.fn(),
    getConfig: vi.fn().mockReturnValue({ debug: false }),
  }

  // ONE handler per file: init() attaches document listeners that are never
  // removed (see handler.optimistic.test.ts).
  beforeAll(() => {
    const handler = new UnifiedEventHandler(appMock as unknown as PyWireApp)
    handler.init()
  })

  beforeEach(() => {
    document.body.innerHTML = ''
    vi.mocked(clearPending).mockClear()
    appMock.httpFormSubmit.mockClear()
  })

  function makeForm(): HTMLFormElement {
    document.body.innerHTML =
      '<form id="f" data-on-submit="save" data-modifiers-submit="optimistic optimistic-class-done">' +
      '<input name="title" value="hi"><button type="submit">Go</button>' +
      '</form>'
    return document.getElementById('f') as HTMLFormElement
  }

  function submit(form: HTMLFormElement): void {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  }

  it('applies the prediction synchronously before httpFormSubmit', () => {
    const form = makeForm()
    submit(form)

    expect(form.hasAttribute('data-pw-pending')).toBe(true)
    expect(form.classList.contains('done')).toBe(true)
    expect(appMock.httpFormSubmit).toHaveBeenCalledTimes(1)
    expect(appMock.sendEvent).not.toHaveBeenCalled()
  })

  it('guards against double-submit while the POST is pending', () => {
    const form = makeForm()
    submit(form)
    submit(form)
    expect(appMock.httpFormSubmit).toHaveBeenCalledTimes(1)

    // Response arrives: the morph strips the marker, clearPending flushes the
    // tracking entry — the next submit goes through again.
    form.removeAttribute('data-pw-pending')
    clearPending()
    submit(form)
    expect(appMock.httpFormSubmit).toHaveBeenCalledTimes(2)
  })

  it('httpFormSubmit calls clearPending after the full-document update', async () => {
    const app = new PyWireApp({ autoInit: false, interactive: false })
    const form = document.createElement('form')
    document.body.appendChild(form)

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        redirected: false,
        text: async () => '<html><body>done</body></html>',
      })
    )
    const updateMock = (app as unknown as { updater: { update: ReturnType<typeof vi.fn> } }).updater
      .update

    await app.httpFormSubmit(form, 'save')

    expect(updateMock).toHaveBeenCalledTimes(1)
    expect(clearPending).toHaveBeenCalledTimes(1)
    // clearPending must run AFTER the morph — before it, the markers are still
    // on the elements and nothing would be flushed.
    expect(vi.mocked(clearPending).mock.invocationCallOrder[0]).toBeGreaterThan(
      updateMock.mock.invocationCallOrder[0]
    )
    vi.unstubAllGlobals()
  })
})
