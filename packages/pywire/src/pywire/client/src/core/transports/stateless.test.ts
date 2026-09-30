import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { encode, decode } from '@msgpack/msgpack'
import { StatelessTransport } from './stateless'
import type { ServerMessage } from './base'

const fetchMock = vi.fn()

/** Minimal Response-like object — avoids happy-dom Response quirks. */
function res(status: number, body: Uint8Array | string, extra: Partial<Response> = {}): Response {
  const isText = typeof body === 'string'
  return {
    ok: status >= 200 && status < 300,
    status,
    redirected: false,
    arrayBuffer: async () => (isText ? new TextEncoder().encode(body).buffer : body.slice().buffer),
    text: async () => (isText ? body : new TextDecoder().decode(body)),
    ...extra,
  } as Response
}

function msgpackRes(status: number, payload: object, extra: Partial<Response> = {}): Response {
  return res(status, encode(payload), extra)
}

function eventMsg(handler = 'increment', path = '/counter') {
  return { type: 'event', handler, path, data: { type: 'click' } }
}

/** Body of the n-th fetch call, msgpack-decoded. */
function sentBody(n: number): Record<string, unknown> {
  return decode(fetchMock.mock.calls[n][1].body as Uint8Array) as Record<string, unknown>
}

describe('StatelessTransport', () => {
  let transport: StatelessTransport
  let messages: ServerMessage[]

  beforeEach(() => {
    vi.clearAllMocks()
    document.body.innerHTML = ''
    document.getElementById('_pywire_spa_meta')?.remove()

    const snap = document.createElement('script')
    snap.id = '_pywire_snapshot'
    snap.type = 'text/plain'
    snap.textContent = 'SNAP_V1'
    document.body.appendChild(snap)

    vi.stubGlobal('fetch', fetchMock)

    transport = new StatelessTransport()
    messages = []
    transport.onMessage((m) => messages.push(m))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('connects without network, reports status, and emits init', async () => {
    const statuses: boolean[] = []
    transport.onStatusChange((c) => statuses.push(c))
    await transport.connect()
    expect(fetchMock).not.toHaveBeenCalled()
    expect(statuses).toEqual([true])
    expect(messages.some((m) => m.type === 'init')).toBe(true)
  })

  it('(a) event POST body decodes to {path, handler, data, snapshot}', async () => {
    fetchMock.mockResolvedValueOnce(
      msgpackRes(200, { type: 'update', regions: [], snapshot: 'SNAP_V2' })
    )
    transport.send(eventMsg())

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/_pywire/stateless')
    expect(init.method).toBe('POST')
    expect(sentBody(0)).toEqual({
      path: '/counter',
      handler: 'increment',
      data: { type: 'click' },
      snapshot: 'SNAP_V1',
    })
    expect(messages.some((m) => m.type === 'update')).toBe(true)
  })

  it('(b)+(c) response snapshot replaces the held one; second event POSTs the NEW snapshot', async () => {
    fetchMock.mockResolvedValueOnce(
      msgpackRes(200, { type: 'update', regions: [], snapshot: 'SNAP_V2' })
    )
    transport.send(eventMsg())
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))

    fetchMock.mockResolvedValueOnce(
      msgpackRes(200, { type: 'update', regions: [], snapshot: 'SNAP_V3' })
    )
    transport.send(eventMsg())
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))

    expect(sentBody(1).snapshot).toBe('SNAP_V2')
  })

  it('marks each reply, success or error, with its event id as ack', async () => {
    fetchMock.mockResolvedValueOnce(
      msgpackRes(200, { type: 'update', regions: [], snapshot: 'SNAP_V2' })
    )
    fetchMock.mockResolvedValueOnce(msgpackRes(400, { error: 'invalid handler' }))
    transport.send({ ...eventMsg(), id: 7 })
    transport.send({ ...eventMsg(), id: 8 })

    await vi.waitFor(() => expect(messages.filter((m) => m.ack !== undefined)).toHaveLength(2))
    const replies = messages.filter((m) => m.ack !== undefined)
    expect(replies.map((m) => [m.type, m.ack])).toEqual([
      ['update', 7],
      ['error', 8],
    ])
  })

  it('(d) HTTP 400 msgpack {error} → {type:"error", error} notified', async () => {
    fetchMock.mockResolvedValueOnce(msgpackRes(400, { error: 'invalid handler' }))
    transport.send(eventMsg())

    await vi.waitFor(() => {
      const err = messages.find((m) => m.type === 'error')
      expect(err).toBeDefined()
      expect(err?.error).toBe('invalid handler')
    })
  })

  it.each([
    ['a rejected snapshot', msgpackRes(400, { error: 'invalid snapshot' })],
    ['an oversized snapshot', msgpackRes(413, { error: 'snapshot too large' })],
    ['a proxy 413 page', res(413, '<html>Request Entity Too Large</html>')],
  ])('reloads for a fresh snapshot after %s', async (_label, response) => {
    fetchMock.mockResolvedValueOnce(response)
    transport.send(eventMsg())

    await vi.waitFor(() => expect(messages.some((m) => m.type === 'reload')).toBe(true))
    expect(messages.some((m) => m.type === 'error')).toBe(false)
  })

  it('network failure → error notified, transport stays connected', async () => {
    await transport.connect()
    fetchMock.mockRejectedValueOnce(new Error('offline'))
    transport.send(eventMsg())

    await vi.waitFor(() => {
      const err = messages.find((m) => m.type === 'error')
      expect(err).toBeDefined()
    })
    expect(transport.isConnected()).toBe(true)
  })

  it('(e) relocate GETs the path, emits full-document update, re-extracts snapshot', async () => {
    const html =
      '<!DOCTYPE html><html><body><h1>Page 2</h1>' +
      '<script id="_pywire_snapshot" type="text/plain">SNAP_PAGE2</script>' +
      '</body></html>'
    fetchMock.mockResolvedValueOnce(res(200, html))
    transport.send({ type: 'relocate', path: '/page2' })

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(fetchMock.mock.calls[0][0]).toBe('/page2')

    const upd = messages.find((m) => m.type === 'update')
    expect(upd?.html).toContain('Page 2')

    // Snapshot was re-extracted: the next event POSTs it.
    fetchMock.mockResolvedValueOnce(
      msgpackRes(200, { type: 'update', regions: [], snapshot: 'SNAP_V3' })
    )
    transport.send(eventMsg('go', '/page2'))
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(sentBody(1).snapshot).toBe('SNAP_PAGE2')
  })

  it('relocate to a 404 emits reload (error pages carry no snapshot)', async () => {
    fetchMock.mockResolvedValueOnce(res(404, '<html><body>Not Found</body></html>'))
    transport.send({ type: 'relocate', path: '/missing' })

    await vi.waitFor(() => {
      expect(messages.some((m) => m.type === 'reload')).toBe(true)
    })
    expect(messages.some((m) => m.type === 'update')).toBe(false)
  })

  it('relocate to a 200 page WITHOUT a snapshot emits reload (full-document fallback)', async () => {
    fetchMock.mockResolvedValueOnce(res(200, '<html><body>no snapshot here</body></html>'))
    transport.send({ type: 'relocate', path: '/plain' })

    await vi.waitFor(() => {
      expect(messages.some((m) => m.type === 'reload')).toBe(true)
    })
    // No stateless POST possible afterwards — but must not crash.
    expect(messages.some((m) => m.type === 'update')).toBe(false)
  })

  it('relocate following a redirect re-navigates to the final URL', async () => {
    fetchMock.mockResolvedValueOnce(
      res(200, '<html><body>ok</body></html>', {
        redirected: true,
        url: 'http://localhost:3010/final?x=1',
      })
    )
    transport.send({ type: 'relocate', path: '/old' })

    await vi.waitFor(() => {
      const nav = messages.find((m) => m.type === 'navigate')
      expect(nav?.path).toBe('/final?x=1')
    })
  })

  it('serializes events: the second POST only fires after the first response', async () => {
    let releaseFirst!: () => void
    const firstResponse = new Promise<void>((r) => {
      releaseFirst = r
    })
    fetchMock.mockImplementationOnce(async () => {
      await firstResponse
      return msgpackRes(200, { type: 'update', regions: [], snapshot: 'S2' })
    })
    fetchMock.mockResolvedValueOnce(
      msgpackRes(200, { type: 'update', regions: [], snapshot: 'S3' })
    )

    transport.send(eventMsg())
    transport.send(eventMsg())
    await new Promise((r) => setTimeout(r, 10))
    // Second event is queued behind the first
    expect(fetchMock).toHaveBeenCalledTimes(1)

    releaseFirst()
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    // Carries the snapshot from the first response, not the stale one
    expect(sentBody(1).snapshot).toBe('S2')
  })

  describe('shared-state refresh', () => {
    function liveTransport(ms: string | null): StatelessTransport {
      const tag = document.getElementById('_pywire_snapshot')!
      if (ms === null) tag.removeAttribute('data-live-every')
      else tag.setAttribute('data-live-every', ms)
      const t = new StatelessTransport()
      t.onMessage((m) => messages.push(m))
      return t
    }

    function setHidden(hidden: boolean): void {
      Object.defineProperty(document, 'visibilityState', {
        configurable: true,
        get: () => (hidden ? 'hidden' : 'visible'),
      })
      document.dispatchEvent(new Event('visibilitychange'))
    }

    beforeEach(() => {
      vi.useFakeTimers()
    })

    afterEach(() => {
      transport.disconnect()
      setHidden(false)
      vi.useRealTimers()
    })

    it('POSTs a handler-less refresh on the interval from the snapshot tag', async () => {
      fetchMock.mockResolvedValue(
        msgpackRes(200, { type: 'update', regions: [], snapshot: 'SNAP_V2', live_every: 2000 })
      )
      transport = liveTransport('2000')
      await transport.connect()

      await vi.advanceTimersByTimeAsync(1999)
      expect(fetchMock).not.toHaveBeenCalled()
      await vi.advanceTimersByTimeAsync(1)
      expect(fetchMock).toHaveBeenCalledTimes(1)
      expect(sentBody(0)).toMatchObject({
        handler: '',
        snapshot: 'SNAP_V1',
        data: { type: 'live' },
      })

      // The reply restarts the countdown and carries the next snapshot.
      await vi.advanceTimersByTimeAsync(2000)
      expect(fetchMock).toHaveBeenCalledTimes(2)
      expect(sentBody(1).snapshot).toBe('SNAP_V2')
    })

    it('never refreshes a page without shared state', async () => {
      transport = liveTransport(null)
      await transport.connect()
      await vi.advanceTimersByTimeAsync(60_000)
      expect(fetchMock).not.toHaveBeenCalled()
    })

    it('refresh replies carry no ack and a failed refresh raises no error', async () => {
      fetchMock
        .mockResolvedValueOnce(
          msgpackRes(200, { type: 'update', regions: [], snapshot: 'S2', live_every: 1000 })
        )
        .mockResolvedValueOnce(msgpackRes(500, { error: 'event failed' }))
      transport = liveTransport('1000')
      await transport.connect()
      messages.length = 0

      await vi.advanceTimersByTimeAsync(1000)
      await vi.advanceTimersByTimeAsync(1000)
      expect(fetchMock).toHaveBeenCalledTimes(2)
      expect(messages).toHaveLength(1)
      expect(messages[0].type).toBe('update')
      expect(messages[0].ack).toBeUndefined()
    })

    it('an event reply sets the interval, and live_every 0 stops refreshing', async () => {
      fetchMock.mockResolvedValueOnce(
        msgpackRes(200, { type: 'update', regions: [], snapshot: 'S2', live_every: 500 })
      )
      fetchMock.mockResolvedValueOnce(
        msgpackRes(200, { type: 'update', regions: [], snapshot: 'S3', live_every: 0 })
      )
      transport = liveTransport(null)
      await transport.connect()
      transport.send(eventMsg())
      await vi.advanceTimersByTimeAsync(0)
      expect(fetchMock).toHaveBeenCalledTimes(1)

      await vi.advanceTimersByTimeAsync(500)
      expect(fetchMock).toHaveBeenCalledTimes(2)
      await vi.advanceTimersByTimeAsync(10_000)
      expect(fetchMock).toHaveBeenCalledTimes(2)
    })

    it('an event postpones the next refresh instead of queueing one behind it', async () => {
      fetchMock.mockResolvedValue(
        msgpackRes(200, { type: 'update', regions: [], snapshot: 'S2', live_every: 1000 })
      )
      transport = liveTransport('1000')
      await transport.connect()

      await vi.advanceTimersByTimeAsync(900)
      transport.send(eventMsg())
      await vi.advanceTimersByTimeAsync(100)
      expect(fetchMock).toHaveBeenCalledTimes(1)
      expect(sentBody(0).handler).toBe('increment')

      await vi.advanceTimersByTimeAsync(900)
      expect(fetchMock).toHaveBeenCalledTimes(2)
      expect(sentBody(1).handler).toBe('')
    })

    it('pauses while the tab is hidden and refreshes as soon as it is visible', async () => {
      fetchMock.mockResolvedValue(
        msgpackRes(200, { type: 'update', regions: [], snapshot: 'S2', live_every: 1000 })
      )
      transport = liveTransport('1000')
      await transport.connect()

      setHidden(true)
      await vi.advanceTimersByTimeAsync(10_000)
      expect(fetchMock).not.toHaveBeenCalled()

      setHidden(false)
      await vi.advanceTimersByTimeAsync(0)
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })
  })
})
