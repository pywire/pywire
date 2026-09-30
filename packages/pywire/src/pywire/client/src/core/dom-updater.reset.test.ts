import { describe, it, expect, beforeEach } from 'vitest'
import { DOMUpdater } from './dom-updater'

// form.reset() / load() on the server bumps data-pw-reset on the <form>; the
// morph then shows the server's values even where the rendered value is the
// same as before and the user has typed over it.
describe('DOMUpdater — a reset bound form shows the server values', () => {
  let updater: DOMUpdater

  const region = (resets: number | null, value = ''): string =>
    `<div data-pw-region="r1"><form data-pw-form="f"${
      resets === null ? '' : ` data-pw-reset="${resets}"`
    }>` +
    `<input id="name" name="name" value="${value}">` +
    `<input id="agree" name="agree" type="checkbox">` +
    `<select id="size" name="size"><option value="s">S</option><option value="m">M</option></select>` +
    `</form></div>`

  const el = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T

  beforeEach(() => {
    updater = new DOMUpdater()
    document.body.innerHTML = region(null)
    el<HTMLInputElement>('name').value = 'typed'
    el<HTMLInputElement>('agree').checked = true
    el<HTMLSelectElement>('size').value = 'm'
  })

  it('keeps what the user typed on an ordinary update', () => {
    updater.updateRegion('r1', region(null))
    expect(el<HTMLInputElement>('name').value).toBe('typed')
    expect(el<HTMLInputElement>('agree').checked).toBe(true)
    expect(el<HTMLSelectElement>('size').value).toBe('m')
  })

  it('clears typed values when the form was reset', () => {
    updater.updateRegion('r1', region(1))
    expect(el<HTMLInputElement>('name').value).toBe('')
    expect(el<HTMLInputElement>('agree').checked).toBe(false)
    expect(el<HTMLSelectElement>('size').value).toBe('s')
  })

  it('clears a focused input too, and only for that update', () => {
    el<HTMLInputElement>('name').focus()
    updater.updateRegion('r1', region(1))
    expect(el<HTMLInputElement>('name').value).toBe('')

    el<HTMLInputElement>('name').value = 'again'
    updater.updateRegion('r1', region(1))
    expect(el<HTMLInputElement>('name').value).toBe('again')
  })

  it('tells listeners the form was reset', () => {
    let seen: EventTarget | null = null
    document.addEventListener('pywire:form-reset', (e) => (seen = e.target), { once: true })
    updater.updateRegion('r1', region(2))
    expect(seen).toBe(document.querySelector('form'))
  })
})
