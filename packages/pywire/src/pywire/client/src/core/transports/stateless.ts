import { BaseTransport, ServerMessage, EventMessage, RelocateMessage } from './base'
import { encode, decode } from '@msgpack/msgpack'
import { logger } from '../logger'
import { getMountPath } from '../mount-path'

/** Server response for a stateless POST: a WS-shaped message plus the next snapshot. */
type StatelessResponse = ServerMessage & { snapshot?: unknown }

/**
 * Transport for stateless (client-held state) mode. There is no persistent
 * channel: every event POSTs the signed page snapshot to
 * ``/_pywire/stateless`` and receives the next snapshot in the response;
 * SPA navigation is a plain GET whose HTML carries a fresh embedded
 * snapshot (``#_pywire_snapshot`` script tag). All state lives with the
 * client — the server keeps nothing between requests.
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

  constructor(baseUrl?: string) {
    super()
    this.baseUrl = baseUrl || `${getMountPath()}/_pywire`
    this.snapshot = document.getElementById('_pywire_snapshot')?.textContent?.trim() ?? ''
  }

  async connect(): Promise<void> {
    this.notifyStatus(true)
    // No server channel exists to push init (that's the point of stateless
    // mode) — emit it locally so version-aware handling in the app still fires.
    this.notifyHandlers({ type: 'init', version: this.readServerVersion() })
  }

  send(message: object): void {
    const msg = message as Partial<EventMessage> & Partial<RelocateMessage>
    if (msg.type === 'event') {
      this.enqueue(() => this.postEvent(msg as EventMessage))
    } else if (msg.type === 'relocate') {
      this.enqueue(() => this.relocate(msg as RelocateMessage))
    }
    // Other message types (init, ref_sync, pong) are session concepts that
    // don't exist without a persistent channel — nothing to send them to.
  }

  disconnect(): void {
    this.notifyStatus(false)
  }

  private enqueue(task: () => Promise<void>): void {
    this.queue = this.queue
      .then(task)
      .catch((e) => logger.error('PyWire: stateless transport request failed', e))
  }

  private async postEvent(msg: EventMessage): Promise<void> {
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
      const payload = decode(await response.arrayBuffer()) as StatelessResponse
      if (!response.ok) {
        this.notifyHandlers({
          type: 'error',
          error:
            typeof payload.error === 'string'
              ? payload.error
              : `stateless request failed: ${response.status}`,
        })
        return
      }
      if (typeof payload.snapshot === 'string') {
        this.snapshot = payload.snapshot
      }
      this.notifyHandlers(payload)
    } catch (e) {
      logger.error('PyWire: stateless event failed', e)
      this.notifyHandlers({ type: 'error', error: 'stateless request failed' })
    }
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
      const snapshot = this.extractSnapshot(html)
      if (!snapshot) {
        // No embedded snapshot (custom __error__ page etc.): this page can't
        // participate in stateless mode — fall back to full document behavior.
        this.notifyHandlers({ type: 'reload' })
        return
      }
      this.snapshot = snapshot
      this.notifyHandlers({ type: 'update', html })
    } catch (e) {
      logger.error('PyWire: stateless navigation failed', e)
      this.notifyHandlers({ type: 'reload' })
    }
  }

  private extractSnapshot(html: string): string {
    try {
      return (
        new DOMParser()
          .parseFromString(html, 'text/html')
          .getElementById('_pywire_snapshot')
          ?.textContent?.trim() ?? ''
      )
    } catch {
      return ''
    }
  }

  /**
   * Best-effort server version for the init message: SPA meta if the server
   * provides one, otherwise the client bundle URL's cache buster (the server
   * version in prod, bundle mtime in dev).
   */
  private readServerVersion(): string {
    const metaEl = document.getElementById('_pywire_spa_meta')
    if (metaEl) {
      try {
        const meta = JSON.parse(metaEl.textContent || '{}')
        if (typeof meta.version === 'string') return meta.version
      } catch {
        /* malformed meta — fall through */
      }
    }
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
