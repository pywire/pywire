import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { UnifiedEventHandler } from './handler'
import { settleForms, releaseForms } from './forms'
import { PyWireApp } from '../core/app'

const FORM = `
  <form id="signup" data-pw-form="signup" data-pw-validate="blur" data-on-submit="_handler_0" method="post">
    <input id="email" name="email" value="">
    <input id="name" name="name" value="">
    <input id="terms" name="terms" type="checkbox" value="true">
    <button id="go" type="submit">Go</button>
  </form>`

describe('bound forms', () => {
  // One handler for the whole file: its document listeners outlive a test,
  // and a second handler would see (and guard) the same submits.
  const app: {
    sendEvent: ReturnType<typeof vi.fn>
    getConfig: ReturnType<typeof vi.fn>
    isInteractive?: boolean
  } = { sendEvent: vi.fn(), getConfig: vi.fn().mockReturnValue({}) }
  const handler = new UnifiedEventHandler(app as unknown as PyWireApp)
  handler.init()
  const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T
  const fire = (id: string, type: string): void => {
    $(id).dispatchEvent(new Event(type, { bubbles: true }))
  }
  const sent = (): Array<[string, Record<string, unknown>]> =>
    app.sendEvent.mock.calls as Array<[string, Record<string, unknown>]>

  beforeEach(() => {
    vi.useFakeTimers()
    document.body.innerHTML = FORM
    app.sendEvent.mockReset()
    app.isInteractive = undefined
  })

  afterEach(() => {
    releaseForms()
    vi.useRealTimers()
  })

  it('validates a field the user typed in when it loses focus', () => {
    $<HTMLInputElement>('email').value = 'nope'
    fire('email', 'input')
    expect(app.sendEvent).not.toHaveBeenCalled()
    fire('email', 'focusout')
    expect(sent()).toHaveLength(1)
    const [name, data] = sent()[0]
    expect(name).toBe('_handler_0')
    expect(data).toMatchObject({
      type: 'validate',
      field: 'email',
      formData: { email: 'nope', name: '' },
    })
  })

  it('does not validate a field the user only tabbed through', () => {
    fire('email', 'focusout')
    expect(app.sendEvent).not.toHaveBeenCalled()
  })

  it('re-validates as the user types while a field shows an error', () => {
    $('email').setAttribute('aria-invalid', 'true')
    fire('email', 'input')
    fire('email', 'input')
    expect(app.sendEvent).not.toHaveBeenCalled()
    vi.advanceTimersByTime(260)
    expect(sent()).toHaveLength(1)
    // Leaving the field right after sends once, not twice.
    fire('email', 'input')
    fire('email', 'focusout')
    vi.advanceTimersByTime(500)
    expect(sent()).toHaveLength(2)
  })

  it('validates a checkbox on change', () => {
    fire('terms', 'change')
    expect(sent()[0][1]).toMatchObject({ type: 'validate', field: 'terms' })
  })

  it('stays quiet for submit-only forms and non-interactive pages', () => {
    $('signup').removeAttribute('data-pw-validate')
    fire('terms', 'change')
    $('signup').setAttribute('data-pw-validate', 'blur')
    app.isInteractive = false
    fire('terms', 'change')
    expect(app.sendEvent).not.toHaveBeenCalled()
  })

  it('guards against a second submit until the server answers', () => {
    const submit = (): void => {
      $('signup').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    }
    submit()
    submit()
    expect(sent().filter(([, d]) => d.type === 'submit')).toHaveLength(1)
    expect($('signup').getAttribute('aria-busy')).toBe('true')

    settleForms()
    expect($('signup').hasAttribute('aria-busy')).toBe(false)
    submit()
    expect(sent().filter(([, d]) => d.type === 'submit')).toHaveLength(2)
  })

  it('focuses the first invalid field once the answer is in', () => {
    $('signup').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    $('name').setAttribute('aria-invalid', 'true')
    settleForms()
    expect(document.activeElement).toBe($('name'))
  })

  it('does not move focus after a failed request', () => {
    $('signup').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    $('name').setAttribute('aria-invalid', 'true')
    releaseForms()
    expect(document.activeElement).not.toBe($('name'))
  })
})
