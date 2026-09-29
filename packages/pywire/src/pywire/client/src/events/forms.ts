/**
 * Bound forms (`<form $bind={...}>`, rendered with `data-pw-form`).
 *
 * A submit marks the form busy until the server answers, which guards it
 * against a second submit. When the answer is applied, focus moves to the
 * first field the server marked invalid.
 */

const SUBMITTING = 'data-pw-submitting'

// Busy forms, with the id of the event that submitted each (null until sent).
const submitting = new Map<HTMLFormElement, number | null>()

/** The name and value of the button that submitted a form, if it has a name. */
export function submitterField(submitter: HTMLElement | null | undefined): [string, string] | null {
  if (
    (submitter instanceof HTMLButtonElement || submitter instanceof HTMLInputElement) &&
    submitter.name
  ) {
    return [submitter.name, submitter.value]
  }
  return null
}

export function isBoundForm(el: Element): el is HTMLFormElement {
  return el instanceof HTMLFormElement && el.hasAttribute('data-pw-form')
}

/** Mark `form` busy. False when a submit is already in flight. */
export function beginSubmit(form: HTMLFormElement): boolean {
  if (form.hasAttribute(SUBMITTING)) return false
  form.setAttribute(SUBMITTING, '')
  form.setAttribute('aria-busy', 'true')
  submitting.set(form, null)
  return true
}

/** The busy `form`'s submit went out as event `id`: its reply settles it. */
export function submitSent(form: HTMLFormElement, id: number): void {
  if (submitting.has(form)) submitting.set(form, id)
}

function release(form: HTMLFormElement): void {
  form.removeAttribute(SUBMITTING)
  form.removeAttribute('aria-busy')
  submitting.delete(form)
}

/**
 * The server answered: release busy forms and focus the first invalid field.
 * With `ack`, only the form whose submit that answers; any other reply (a
 * live check, a poll) leaves a submit in flight busy. Without, every form
 * (an HTTP submit's response).
 */
export function settleForms(ack?: number | null): void {
  for (const [form, id] of Array.from(submitting)) {
    if (ack !== undefined && (ack === null || id !== ack)) continue
    release(form)
    if (!form.isConnected) continue
    const invalid = form.querySelector<HTMLElement>('[aria-invalid="true"]')
    if (invalid && !invalid.contains(document.activeElement)) invalid.focus()
  }
}

/**
 * The request failed: release busy forms without moving focus. With `ack`,
 * only the form whose submit failed.
 */
export function releaseForms(ack?: number | null): void {
  for (const [form, id] of Array.from(submitting)) {
    if (ack == null || id === ack) release(form)
  }
}
