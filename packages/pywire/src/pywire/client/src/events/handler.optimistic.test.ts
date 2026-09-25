import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import { UnifiedEventHandler } from './handler'
import { PyWireApp } from '../core/app'
import { clearPending, revertPending } from './pending'

// Optimistic prediction is presentation-only and applied synchronously on
// dispatch. `data-pw-pending` doubles as the double-submit guard and is stripped
// by the morph when the response arrives (success → morph reconciles classes);
// tracking is per element, so an error reverts only controls still pending.
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

  function makeTwoButtons(): [HTMLButtonElement, HTMLButtonElement] {
    document.body.innerHTML =
      '<button id="b1" data-on-click="doIt" ' +
      'data-modifiers-click="optimistic optimistic-class-done">1</button>' +
      '<button id="b2" data-on-click="doIt" ' +
      'data-modifiers-click="optimistic optimistic-class-done">2</button>'
    return [
      document.getElementById('b1') as HTMLButtonElement,
      document.getElementById('b2') as HTMLButtonElement,
    ]
  }

  /** What the arriving morph does to a reconciled element (see dom-updater.optimistic.test.ts). */
  function reconcile(el: HTMLElement): void {
    el.removeAttribute('data-pw-pending')
    el.removeAttribute('data-pw-pending-disabled')
    if (el instanceof HTMLButtonElement) el.disabled = false
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

  it('keeps the prediction when the morph has not reconciled the element yet', () => {
    const btn = makeButton()
    btn.click()
    expect(btn.disabled).toBe(true)

    // An update arrives for something ELSE — the morph didn't touch btn, so its
    // marker (and its tracking entry) must survive: its response hasn't arrived.
    clearPending() // what app.ts does on {type:'update'}, after the morph

    expect(btn.hasAttribute('data-pw-pending')).toBe(true)
    expect(btn.disabled).toBe(true)

    // Now btn's own response arrives: the morph strips its markers, clearPending
    // flushes the entry, and the class is left alone (the morph owns it).
    reconcile(btn)
    clearPending()
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
    reconcile(btn) // the morph strips markers when the response arrives
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

  it('reverts the SECOND prediction when an error arrives after the first was reconciled', () => {
    const [b1, b2] = makeTwoButtons()
    b1.click()
    b2.click()
    expect(appMock.sendEvent).toHaveBeenCalledTimes(2)

    // b1's response arrives: the morph reconciles b1, clearPending flushes ONLY b1.
    reconcile(b1)
    clearPending()
    expect(b2.hasAttribute('data-pw-pending')).toBe(true)
    expect(b2.disabled).toBe(true)

    // b2's request then errors → its recorded classes still revert, it re-enables.
    revertPending()
    expect(b2.classList.contains('done')).toBe(false)
    expect(b2.hasAttribute('data-pw-pending')).toBe(false)
    expect(b2.disabled).toBe(false)
    // b1 was already reconciled — its (server-owned) class is untouched.
    expect(b1.classList.contains('done')).toBe(true)
  })

  it('reverts BOTH predictions when an error arrives with two requests in flight', () => {
    const [b1, b2] = makeTwoButtons()
    b1.click()
    b2.click()

    revertPending()
    for (const b of [b1, b2]) {
      expect(b.classList.contains('done')).toBe(false)
      expect(b.hasAttribute('data-pw-pending')).toBe(false)
      expect(b.disabled).toBe(false)
    }
  })

  it('applies the prediction synchronously BEFORE a slow file upload', async () => {
    document.body.innerHTML =
      '<meta name="pywire-upload-token" content="tok">' +
      '<form id="f" data-on-submit="save" data-modifiers-submit="optimistic optimistic-class-saving">' +
      '<input type="file" name="doc">' +
      '<button type="submit">Go</button>' +
      '</form>'
    const form = document.getElementById('f') as HTMLFormElement

    // jsdom clones form-associated Files with size 0, so a real
    // `new FormData(form)` never reports a non-empty file. Stub just enough of
    // FormData for the handler's extraction loop to see one file + one string.
    class FakeFormData {
      append(): void {}
      forEach(cb: (value: FormDataEntryValue, key: string) => void): void {
        cb(new File(['x'], 'a.txt', { type: 'text/plain' }), 'doc')
        cb('hello', 'title')
      }
    }
    vi.stubGlobal('FormData', FakeFormData as unknown as typeof FormData)

    let resolveUpload!: (v: unknown) => void
    const fetchMock = vi.fn().mockReturnValue(new Promise((r) => (resolveUpload = r)))
    vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch)

    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))

    // Same tick, upload still in flight: prediction + guard already applied.
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(form.hasAttribute('data-pw-pending')).toBe(true)
    expect(form.classList.contains('saving')).toBe(true)
    expect(appMock.sendEvent).not.toHaveBeenCalled()

    // A second submit during the upload is guarded — no second upload.
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await Promise.resolve()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    resolveUpload({ ok: true, json: async () => ({ uploads: { doc: 'u1' } }) })
    await vi.waitFor(() => expect(appMock.sendEvent).toHaveBeenCalledTimes(1))
    const sent = appMock.sendEvent.mock.calls[0][1] as { formData: Record<string, unknown> }
    expect(sent.formData).toEqual({ title: 'hello', doc: { _upload_id: 'u1' } })
    vi.unstubAllGlobals()
  })
})
