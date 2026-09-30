import { PyWireApp } from '../core/app'
import { EventData } from '../core/transports'

/**
 * ``@poll`` kernel timer primitive.
 *
 * The server compiles ``@poll={handler}`` / ``@poll.every-<ms>={handler}`` to
 * ``data-pw-poll`` / ``data-pw-poll-every`` (never ``data-on-poll`` — ``poll``
 * is not a DOM event, so it must not become an ``addEventListener`` target).
 * ``schedulePolls`` hooks the same mount/morph/unmount lifecycle the event
 * wiring uses (UnifiedEventHandler.refreshListeners), and each tick runs
 * through ``app.sendEvent`` — the same dispatch path as a click — so the
 * stateless POST and the WebSocket transport both deliver it automatically.
 */

const DEFAULT_INTERVAL = 1000

interface PollState {
  timer: number
  inFlight: boolean
  /** A tick came due while the previous one was in flight. */
  due: boolean
}

/** Running timers per element. Dead entries are dropped on the next rescan. */
const polls = new Map<HTMLElement, PollState>()

/**
 * Rescan the live DOM: start timers for newly-mounted poll elements and drop
 * timers whose element was unmounted, region-replaced, or navigated away.
 * Called from `refreshListeners` after every morph / navigation.
 */
export function schedulePolls(app: PyWireApp): void {
  const live = new Set<HTMLElement>()
  document.querySelectorAll('[data-pw-poll]').forEach((node) => {
    if (node instanceof HTMLElement) {
      live.add(node)
      if (!polls.has(node)) {
        const timer = window.setInterval(() => tick(node, app), pollInterval(node))
        polls.set(node, { timer, inFlight: false, due: false })
      }
    }
  })
  for (const [el, state] of polls) {
    if (!live.has(el) || !el.isConnected) {
      window.clearInterval(state.timer)
      polls.delete(el)
    }
  }
}

/**
 * Mark every poll's in-flight request as complete. Fired on every server
 * response (success or error) — including empty updates, where no morph runs
 * and therefore no rescan happens. Without this, a poll whose handler changes
 * nothing would stay permanently "in flight" and stop ticking.
 *
 * A tick that came due while the request was in flight is sent now rather
 * than dropped, and the interval restarts from it: a response slower than
 * the interval sets the pace instead of waiting for the next whole interval.
 */
export function clearPollInFlight(app: PyWireApp): void {
  for (const [el, state] of polls) {
    state.inFlight = false
    if (!state.due) continue
    state.due = false
    window.clearInterval(state.timer)
    state.timer = window.setInterval(() => tick(el, app), pollInterval(el))
    // After the current response's morph, which may unmount the element.
    window.setTimeout(() => tick(el, app), 0)
  }
}

function pollInterval(el: HTMLElement): number {
  const raw = el.getAttribute('data-pw-poll-every')
  if (raw === null) return DEFAULT_INTERVAL
  const ms = Number.parseInt(raw, 10)
  return Number.isNaN(ms) || ms <= 0 ? DEFAULT_INTERVAL : ms
}

function tick(el: HTMLElement, app: PyWireApp): void {
  const state = polls.get(el)
  if (!state || !el.isConnected) return
  if (state.inFlight) {
    state.due = true
    return
  }
  const handler = el.getAttribute('data-pw-poll')
  if (!handler) return

  // Overlap guard: a tick that comes due while the prior dispatch is still
  // awaiting its response waits for it (see clearPollInFlight), so a slow
  // handler can't pile up concurrent requests.
  state.inFlight = true

  // Lifted args (e.g. `@poll={tick(idx)}` inside `$for`) arrive via data-arg-*,
  // mirroring the click path's getArgs().
  const args: Record<string, unknown> = {}
  for (const key in el.dataset) {
    if (key.startsWith('arg')) {
      try {
        args[key] = JSON.parse(el.dataset[key] || 'null')
      } catch {
        args[key] = el.dataset[key]
      }
    }
  }

  const eventData: EventData = {
    type: 'poll',
    id: el.id || undefined,
    tagName: el.tagName,
    args,
  }
  app.sendEvent(handler, eventData)
}
