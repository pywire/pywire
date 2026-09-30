import { BaseTransport, ServerMessage, EventMessage, RelocateMessage } from './base'
import { encode, decode } from '@msgpack/msgpack'
import { logger } from '../logger'
import { bootSpaMeta, getMountPath } from '../spa-meta'

/** Server response for a stateless POST: a WS-shaped message plus the next snapshot. */
type StatelessResponse = ServerMessage & { snapshot?: unknown; live_every?: unknown }

/**
 * Transport for stateless (client-held state) mode. There is no persistent
 * channel: every event POSTs the signed page snapshot to
 * ``/_pywire/stateless`` and receives the next snapshot in the response;
 * SPA navigation is a plain GET whose HTML carries a fresh embedded
 * snapshot (``#_pywire_snapshot`` script tag). All state lives with the
 * client — the server keeps nothing between requests.
 *
 * Pages that show shared state (module-level wires, producers) can't be
 * pushed to, so the server tells the client how often to re-read it
 * (``data-live-every`` on the snapshot tag, ``live_every`` on replies, in
 * ms). The transport then POSTs a handler-less refresh on that interval,
 * paused while the tab is hidden; every reply restarts the countdown, since
 * the server refreshes shared regions on every request.
 */
export class StatelessTransport extends BaseTransport {
  readonly name = 'Stateless'

  private snapshot = ''
  private readonly baseUrl: string
  /**
   * Serializes requests: each event must carry the snapshot produced by its
   * predecessor, so at most one POST/relocate is in flight at a time.
   */
  private queue: Promise<void> = Promise.resolve()
  /** Shared-state refresh interval in ms; 0 = this page has none. */
  private liveEvery = 0
  private liveTimer: number | null = null
  /** A refresh is waiting in `queue`; don't stack another behind it. */
  private liveQueued = false
  private readonly onVisibilityChange = (): void => {
    if (document.visibilityState === 'hidden') {
      this.clearLiveTimer()
    } else if (this.liveEvery > 0) {
      // The tab missed updates while hidden: refresh now, not a tick later.
      this.refreshLive()
    }
  }

  constructor(baseUrl?: string) {
    super()
    this.baseUrl = baseUrl || `${getMountPath()}/_pywire`
    const tag = findSnapshotTag(document)
    this.snapshot = tag?.textContent?.trim() ?? ''
    this.liveEvery = parseLiveEvery(tag?.getAttribute('data-live-every'))
  }

  async connect(): Promise<void> {
    this.notifyStatus(true)
    // No server channel exists to push init (that's the point of stateless
    // mode) — emit it locally so version-aware handling in the app still fires.
    this.notifyHandlers({ type: 'init', version: this.readServerVersion() })
    document.addEventListener('visibilitychange', this.onVisibilityChange)
    this.scheduleLive()
  }

  send(message: object): void {
    const msg = message as Partial<EventMessage> & Partial<RelocateMessage>
    if (msg.type === 'event') {
      // The event's reply refreshes shared state too and restarts the countdown.
      this.clearLiveTimer()
      this.enqueue(() => this.postEvent(msg as EventMessage))
    } else if (msg.type === 'relocate') {
      this.enqueue(() => this.relocate(msg as RelocateMessage))
    }
    // Other message types (init, ref_sync, pong) are session concepts that
    // don't exist without a persistent channel — nothing to send them to.
  }

  disconnect(): void {
    document.removeEventListener('visibilitychange', this.onVisibilityChange)
    this.clearLiveTimer()
    this.notifyStatus(false)
  }

  private enqueue(task: () => Promise<void>): void {
    this.queue = this.queue
      .then(task)
      .catch((e) => logger.error('PyWire: stateless transport request failed', e))
      .finally(() => this.scheduleLive())
  }

  private clearLiveTimer(): void {
    if (this.liveTimer !== null) {
      window.clearTimeout(this.liveTimer)
      this.liveTimer = null
    }
  }

  /** (Re)start the countdown to the next shared-state refresh. */
  private scheduleLive(): void {
    this.clearLiveTimer()
    if (this.liveEvery <= 0 || document.visibilityState === 'hidden') return
    this.liveTimer = window.setTimeout(() => this.refreshLive(), this.liveEvery)
  }

  private refreshLive(): void {
    this.clearLiveTimer()
    if (this.liveQueued) return
    this.liveQueued = true
    this.enqueue(async () => {
      this.liveQueued = false
      await this.postEvent({
        type: 'event',
        handler: '',
        path: window.location.pathname + window.location.search,
        data: { type: 'live' },
      })
    })
  }

  private async postEvent(msg: EventMessage): Promise<void> {
    // A shared-state refresh is a server push in all but transport: no ack,
    // and a failed one waits for the next tick instead of surfacing an error.
    const isRefresh = !msg.handler
    try {
      const response = await fetch(`${this.baseUrl}/stateless`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-msgpack',
          Accept: 'application/x-msgpack',
        },
        credentials: 'same-origin',
        body: encode({
          path: msg.path,
          handler: msg.handler,
          data: msg.data,
          snapshot: this.snapshot,
        }),
      })
      // The snapshot is over the size cap (possibly rejected by a proxy with
      // a body that isn't msgpack): every later event would fail the same way.
      if (response.status === 413) {
        this.reloadForFreshSnapshot('snapshot too large')
        return
      }
      const payload = decode(await response.arrayBuffer()) as StatelessResponse
      if (!response.ok) {
        const error =
          typeof payload.error === 'string'
            ? payload.error
            : `stateless request failed: ${response.status}`
        // Signed with a rotated key or before a deploy, or issued for another
        // URL: this snapshot will never be accepted again.
        if (response.status === 400 && error === 'invalid snapshot') {
          this.reloadForFreshSnapshot(error)
          return
        }
        if (isRefresh) {
          logger.warn(`PyWire: shared-state refresh failed: ${error}`)
          return
        }
        this.notifyHandlers({ type: 'error', error, ack: msg.id })
        return
      }
      if (typeof payload.snapshot === 'string') {
        this.snapshot = payload.snapshot
      }
      if (payload.live_every !== undefined) {
        this.liveEvery = parseLiveEvery(payload.live_every)
      }
      this.notifyHandlers(isRefresh ? payload : { ...payload, ack: msg.id })
    } catch (e) {
      logger.error('PyWire: stateless event failed', e)
      if (!isRefresh) {
        this.notifyHandlers({ type: 'error', error: 'stateless request failed', ack: msg.id })
      }
    }
  }

  /** Reload the page: its HTML embeds a snapshot the server will accept. */
  private reloadForFreshSnapshot(reason: string): void {
    logger.warn(`PyWire: ${reason}; reloading the page`)
    this.notifyHandlers({ type: 'reload' })
  }

  private async relocate(msg: RelocateMessage): Promise<void> {
    let response: Response
    try {
      // Plain GET — no X-PyWire-Internal header: the stateless snapshot is
      // only embedded on full (non-internal) page renders.
      response = await fetch(msg.path, {
        headers: { Accept: 'text/html' },
        credentials: 'same-origin',
      })
    } catch (e) {
      logger.error('PyWire: stateless navigation failed', e)
      this.notifyHandlers({ type: 'reload' })
      return
    }

    if (response.redirected) {
      // Follow it via the app's navigate path (pushState + new relocate).
      const url = new URL(response.url)
      this.notifyHandlers({ type: 'navigate', path: url.pathname + url.search })
      return
    }

    if (!response.ok) {
      // Error pages are a different document (own <head>, no snapshot) —
      // morphing them into the live DOM would leak the error template.
      // Full reload lets the browser render the page cleanly.
      this.notifyHandlers({ type: 'reload' })
      return
    }

    try {
      const html = await response.text()
      const { snapshot, liveEvery } = this.extractSnapshot(html)
      if (!snapshot) {
        // No embedded snapshot (custom __error__ page etc.): this page can't
        // participate in stateless mode — fall back to full document behavior.
        this.notifyHandlers({ type: 'reload' })
        return
      }
      this.snapshot = snapshot
      this.liveEvery = liveEvery
      this.notifyHandlers({ type: 'update', html })
    } catch (e) {
      logger.error('PyWire: stateless navigation failed', e)
      this.notifyHandlers({ type: 'reload' })
    }
  }

  private extractSnapshot(html: string): { snapshot: string; liveEvery: number } {
    try {
      const tag = findSnapshotTag(new DOMParser().parseFromString(html, 'text/html'))
      return {
        snapshot: tag?.textContent?.trim() ?? '',
        liveEvery: parseLiveEvery(tag?.getAttribute('data-live-every')),
      }
    } catch {
      return { snapshot: '', liveEvery: 0 }
    }
  }

  /**
   * Best-effort server version for the init message: SPA meta if the server
   * provides one, otherwise the client bundle URL's cache buster (the server
   * version in prod, bundle mtime in dev).
   */
  private readServerVersion(): string {
    const version = bootSpaMeta().version
    if (typeof version === 'string') return version
    const script = document.querySelector<HTMLScriptElement>('script[src*="/_pywire/static/"]')
    if (script?.src) {
      try {
        return new URL(script.src, window.location.href).searchParams.get('v') ?? ''
      } catch {
        /* odd src — give up */
      }
    }
    return ''
  }
}

/**
 * The snapshot the server embedded: a text `<script>` after all page markup,
 * so the last one — never another element that carries the id.
 */
function findSnapshotTag(root: ParentNode): HTMLScriptElement | null {
  const tags = root.querySelectorAll<HTMLScriptElement>(
    'script#_pywire_snapshot[type="text/plain"]'
  )
  return tags.length ? tags[tags.length - 1] : null
}

/** A refresh interval in ms from the server; anything unusable means none. */
function parseLiveEvery(raw: unknown): number {
  const ms = typeof raw === 'number' ? raw : Number.parseInt(String(raw ?? ''), 10)
  return Number.isFinite(ms) && ms > 0 ? ms : 0
}
