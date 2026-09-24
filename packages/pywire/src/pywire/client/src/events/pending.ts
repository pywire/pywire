/**
 * Optimistic prediction state (plan spec #7 / review focus #8).
 *
 * Predictions are presentation-only and applied SYNCHRONOUSLY on dispatch (see
 * handler.ts). `data-pw-pending` never exists in server HTML, so the arriving
 * morphdom patch strips it — that strip is the "request finished" signal, and
 * while it is present the control is guarded against double-submit.
 *
 * Reconciliation:
 * - Success (`clearPending`): the morph is the ONLY reconciler. Markers are
 *   cleared here as a safety net for elements outside the patched region, but
 *   predicted classes are left alone — the server HTML owns them.
 * - Error (`revertPending`): no morph arrives, so we must undo the classes we
 *   added and re-enable any control we disabled. A control is never left stuck.
 */

const PENDING = 'data-pw-pending'
const PENDING_DISABLED = 'data-pw-pending-disabled'
const CLASS_PREFIX = 'optimistic-class-'

interface Prediction {
  el: HTMLElement
  classes: string[]
}

/** Optimistic predictions applied since the last update/error. */
let predictions: Prediction[] = []

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
 * synchronously immediately before transport.send.
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

  predictions.push({ el, classes })
}

/** Remove pending markers and re-enable any control we disabled. */
function clearMarkers(): void {
  document.querySelectorAll(`[${PENDING}]`).forEach((el) => el.removeAttribute(PENDING))
  document.querySelectorAll(`[${PENDING_DISABLED}]`).forEach((el) => {
    el.removeAttribute(PENDING_DISABLED)
    ;(el as HTMLButtonElement).disabled = false
  })
}

/** On a successful update: clear leftover markers, keep classes (morph owns them). */
export function clearPending(): void {
  clearMarkers()
  predictions = []
}

/** On an error response: also revert predicted classes, then clear markers. */
export function revertPending(): void {
  for (const { el, classes } of predictions) {
    for (const c of classes) el.classList.remove(c)
  }
  clearMarkers()
  predictions = []
}
