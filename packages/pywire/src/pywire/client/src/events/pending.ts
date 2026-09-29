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
 * response clobber the predictions of controls still in flight), and each
 * prediction is bound to the id of the event it sent. Replies to an event
 * echo that id as `ack`; events are answered in order, so an ack settles
 * every prediction with an id up to it:
 * - Success (`clearPending`, called after the morph): flush entries whose
 *   marker is gone — the morph reconciled them and the server HTML owns their
 *   classes. An answered entry the morph never reached (its region didn't
 *   re-render) is reverted: the server HTML for it didn't change. Other
 *   entries belong to requests still in flight; they stay tracked and guarded.
 * - Error (`revertPending`): revert answered entries, or every entry when the
 *   error names no event. No morph arrives, so we undo the classes we added
 *   and re-enable any control we disabled. A control is never left stuck.
 */

const PENDING = 'data-pw-pending'
const PENDING_DISABLED = 'data-pw-pending-disabled'
const CLASS_PREFIX = 'optimistic-class-'

interface Prediction {
  classes: string[]
  /** Id of the event sent for this prediction; null until it is sent. */
  eventId: number | null
}

/** Predictions for every element still awaiting its response. */
const predictions = new Map<HTMLElement, Prediction>()

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

  predictions.set(el, { classes, eventId: null })
}

/** Bind `el`'s prediction to the event just sent for it. */
export function bindPending(el: HTMLElement, eventId: number): void {
  const prediction = predictions.get(el)
  if (prediction) prediction.eventId = eventId
}

/** Undo one element's prediction: classes, marker, and the disable we added. */
export function revertElement(el: HTMLElement): void {
  const prediction = predictions.get(el)
  if (prediction === undefined) return
  for (const c of prediction.classes) el.classList.remove(c)
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

/** True when the reply acknowledging event `ack` also answers `prediction`. */
function answered(prediction: Prediction, ack: number | undefined): boolean {
  return ack !== undefined && prediction.eventId !== null && prediction.eventId <= ack
}

/**
 * On a successful update (after the morph has been applied): drop entries the
 * morph reconciled and revert answered ones it never reached; entries still
 * marked are in-flight requests — leave them tracked and guarded. `ack` is the
 * id of the event this update answers (absent for server pushes).
 */
export function clearPending(ack?: number): void {
  for (const [el, prediction] of predictions) {
    if (reconciled(el)) predictions.delete(el)
    else if (answered(prediction, ack)) revertElement(el)
  }
}

/**
 * On an error response: revert every element whose event failed (no morph is
 * coming for those), and drop already-reconciled entries. Without an `ack`
 * the failed request is unknown, so every pending element is reverted.
 */
export function revertPending(ack?: number): void {
  for (const [el, prediction] of predictions) {
    if (reconciled(el)) predictions.delete(el)
    else if (ack === undefined || answered(prediction, ack)) revertElement(el)
  }
}
