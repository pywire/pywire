/**
 * Optimistic prediction state (plan spec #7 / review focus #8).
 *
 * Predictions are presentation-only and applied SYNCHRONOUSLY on dispatch (see
 * handler.ts). `data-pw-pending` never exists in server HTML, so the morphdom
 * patch that covers an element strips its marker — that strip is the
 * per-element "request finished" signal, and while it is present the control
 * is guarded against double-submit.
 *
 * Tracking is PER ELEMENT (one shared list would let the first arriving
 * response clobber the predictions of controls still in flight):
 * - Success (`clearPending`, called after the morph): flush entries whose
 *   marker is gone — the morph reconciled them and the server HTML owns their
 *   classes. Entries still carrying a marker belong to requests whose response
 *   has NOT arrived; they stay tracked and guarded.
 * - Error (`revertPending`): revert entries still carrying a marker — in the
 *   transports' queue models the error corresponds to the outstanding
 *   requests. No morph arrives, so we undo the classes we added and re-enable
 *   any control we disabled. A control is never left stuck.
 */

const PENDING = 'data-pw-pending'
const PENDING_DISABLED = 'data-pw-pending-disabled'
const CLASS_PREFIX = 'optimistic-class-'

/** Predicted classes for every element still awaiting its response. */
const predictions = new Map<HTMLElement, string[]>()

/** True when modifiers request optimistic behavior (bare token or any class token). */
export function isOptimistic(modifiers: string[]): boolean {
  return modifiers.some((m) => m === 'optimistic' || m.startsWith(CLASS_PREFIX))
}

function isGuardable(el: HTMLElement): boolean {
  return (
    el.tagName === 'BUTTON' ||
    (el.tagName === 'INPUT' && (el as HTMLInputElement).type === 'submit')
  )
}

/**
 * Apply the optimistic prediction to `el`: mark it pending, add each predicted
 * class, and disable guarded controls (remembering it was us). Called
 * synchronously immediately before transport.send (and before any async file
 * upload, so the guard covers the upload too).
 */
export function applyOptimistic(el: HTMLElement, modifiers: string[]): void {
  const classes = modifiers
    .filter((m) => m.startsWith(CLASS_PREFIX))
    .map((m) => m.slice(CLASS_PREFIX.length))
    .filter((c) => c.length > 0)

  el.setAttribute(PENDING, '')
  for (const c of classes) el.classList.add(c)

  if (isGuardable(el)) {
    el.setAttribute(PENDING_DISABLED, '')
    ;(el as HTMLButtonElement).disabled = true
  }

  predictions.set(el, classes)
}

/** Undo one element's prediction: classes, marker, and the disable we added. */
export function revertElement(el: HTMLElement): void {
  const classes = predictions.get(el)
  if (classes === undefined) return
  for (const c of classes) el.classList.remove(c)
  el.removeAttribute(PENDING)
  if (el.hasAttribute(PENDING_DISABLED)) {
    el.removeAttribute(PENDING_DISABLED)
    ;(el as HTMLButtonElement).disabled = false
  }
  predictions.delete(el)
}

/** True when the morph reconciled this element (or replaced it outright). */
function reconciled(el: HTMLElement): boolean {
  return !el.isConnected || !el.hasAttribute(PENDING)
}

/**
 * On a successful update (after the morph has been applied): drop entries the
 * morph reconciled; entries still marked are in-flight requests whose response
 * hasn't arrived yet — leave them tracked and guarded.
 */
export function clearPending(): void {
  for (const el of predictions.keys()) {
    if (reconciled(el)) predictions.delete(el)
  }
}

/**
 * On an error response: revert every element still awaiting its response (no
 * morph is coming for those), and drop already-reconciled entries.
 */
export function revertPending(): void {
  for (const el of predictions.keys()) {
    if (reconciled(el)) predictions.delete(el)
    else revertElement(el)
  }
}
