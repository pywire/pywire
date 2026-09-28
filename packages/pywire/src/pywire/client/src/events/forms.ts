/**
 * Bound forms (`<form $bind={...}>`, rendered with `data-pw-form`).
 *
 * A submit marks the form busy until the server answers, which guards it
 * against a second submit. When the answer is applied, focus moves to the
 * first field the server marked invalid.
 */

const SUBMITTING = 'data-pw-submitting'

const submitting = new Set<HTMLFormElement>()

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
  submitting.add(form)
  return true
}

function release(form: HTMLFormElement): void {
  form.removeAttribute(SUBMITTING)
  form.removeAttribute('aria-busy')
  submitting.delete(form)
}

/** The server answered: release busy forms and focus the first invalid field. */
export function settleForms(): void {
  for (const form of Array.from(submitting)) {
    release(form)
    if (!form.isConnected) continue
    const invalid = form.querySelector<HTMLElement>('[aria-invalid="true"]')
    if (invalid && !invalid.contains(document.activeElement)) invalid.focus()
  }
}

/** The request failed: release busy forms without moving focus. */
export function releaseForms(): void {
  for (const form of Array.from(submitting)) release(form)
}
