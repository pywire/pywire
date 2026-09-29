import { describe, it, expect, beforeEach } from 'vitest'
import { DOMUpdater } from './dom-updater'

// Bind echo: every keystroke round-trips through the server, so a patch lands
// while the user is still typing — and it carries the value the server saw
// *before* those keystrokes. Uses the REAL morphdom path (no mock).
// The input must stay user-owned while focused; the server echo only wins when
// nobody is typing.
describe('DOMUpdater — bind echo keeps focused inputs user-owned', () => {
  let updater: DOMUpdater

  const region = (serverValue: string): string =>
    `<div data-pw-region="r1"><input id="field" name="field" value="${serverValue}"></div>`

  const field = (): HTMLInputElement => document.getElementById('field') as HTMLInputElement

  const typeInto = (value: string, caret: number): void => {
    const el = field()
    el.focus()
    el.value = value
    el.setSelectionRange(caret, caret)
  }

  beforeEach(() => {
    updater = new DOMUpdater()
    document.body.innerHTML = region('hello')
  })

  it('keeps text typed ahead of the echo, plus the caret', () => {
    typeInto('hello world', 11)

    // Echo of the state the server saw before " world" was typed.
    updater.updateRegion('r1', region('hello'))

    expect(field().value).toBe('hello world')
    expect(field().selectionStart).toBe(11)
    expect(field().selectionEnd).toBe(11)
    expect(document.activeElement).toBe(field())
  })

  it('keeps an in-flight mid-text edit that is not a prefix of the echo', () => {
    document.body.innerHTML = region('abcde')
    typeInto('abXYcde', 4)

    updater.updateRegion('r1', region('abcde'))

    expect(field().value).toBe('abXYcde')
    expect(field().selectionStart).toBe(4)
    expect(document.activeElement).toBe(field())
  })

  it('keeps a focused input the user just cleared', () => {
    typeInto('', 0)

    updater.updateRegion('r1', region('hello'))

    expect(field().value).toBe('')
    expect(document.activeElement).toBe(field())
  })

  it('applies the server value when nobody is focused (echo must reconcile)', () => {
    field().value = 'stale-local'
    expect(document.activeElement).not.toBe(field())

    updater.updateRegion('r1', region('server-state'))

    expect(field().value).toBe('server-state')
  })
})
