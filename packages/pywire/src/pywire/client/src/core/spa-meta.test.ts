import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { bootSpaMeta, getMountPath, isMountPath, isSameOriginPath, resetSpaMeta } from './spa-meta'
import { WebSocketTransport } from './transports/websocket'
import { HTTPTransport } from './transports/http'
import { StatelessTransport } from './transports/stateless'

/** The server's config script, as page.py renders it: last thing in <body>. */
function serverMeta(meta: object): string {
  return `<script id="_pywire_spa_meta" type="application/json">${JSON.stringify(meta)}</script>`
}

function baseUrl(transport: object): string {
  return (transport as { baseUrl: string }).baseUrl
}

describe('spa meta', () => {
  beforeEach(() => {
    document.head.innerHTML = ''
    document.body.innerHTML = ''
    resetSpaMeta()
  })

  it('reads the server JSON script', () => {
    document.body.innerHTML = serverMeta({ mount_path: '/app', stateless: true })
    expect(getMountPath()).toBe('/app')
    expect(bootSpaMeta().stateless).toBe(true)
  })

  it('ignores page markup that carries the id', () => {
    // A user-chosen id on an ordinary element, with JSON-looking text.
    document.body.innerHTML =
      '<div id="_pywire_spa_meta">{"mount_path": ".evil.example", "stateless": true}</div>' +
      serverMeta({ mount_path: '' })
    expect(getMountPath()).toBe('')
    expect(bootSpaMeta().stateless).toBeUndefined()
    expect(baseUrl(new WebSocketTransport())).toBe(`ws://${window.location.host}/_pywire/ws`)
  })

  it('ignores a non-JSON script that carries the id', () => {
    document.body.innerHTML =
      '<script id="_pywire_spa_meta" type="text/plain">{"mount_path": "/x"}</script>'
    expect(getMountPath()).toBe('')
  })

  it('takes the last JSON script: the server appends its own after the page', () => {
    document.body.innerHTML =
      serverMeta({ mount_path: '/early' }) + serverMeta({ mount_path: '/app' })
    expect(getMountPath()).toBe('/app')
  })

  it('reads the config once', () => {
    document.body.innerHTML = serverMeta({ mount_path: '/app' })
    expect(getMountPath()).toBe('/app')
    document.body.innerHTML = serverMeta({ mount_path: '/other' })
    expect(getMountPath()).toBe('/app')
  })

  it.each([
    '.evil.example',
    '//evil.example',
    '/\\evil.example',
    'https://evil.example',
    '/app/',
    '/a//b',
    ' /app',
    '/a b',
    42,
  ])('rejects mount path %j', (mount) => {
    document.body.innerHTML = serverMeta({ mount_path: mount })
    expect(getMountPath()).toBe('')
  })

  it.each(['', '/app', '/team/app', '/a-b_c.d~e', '/%E2%9C%93'])(
    'accepts mount path %j',
    (mount) => {
      expect(isMountPath(mount)).toBe(true)
    }
  )

  it.each([
    ['/_pywire/dev/reload', true],
    ['/', true],
    ['//evil.example/x', false],
    ['/\\evil.example', false],
    ['https://evil.example/', false],
    ['relative', false],
    ['/a\nb', false],
  ])('same-origin path %j: %s', (value, ok) => {
    expect(isSameOriginPath(value)).toBe(ok)
  })

  describe('transport URLs stay on this origin', () => {
    afterEach(() => {
      vi.unstubAllGlobals()
    })

    it('under a hostile mount path', () => {
      document.body.innerHTML = serverMeta({ mount_path: '//evil.example' })
      const origin = window.location.origin
      expect(baseUrl(new WebSocketTransport())).toBe(`ws://${window.location.host}/_pywire/ws`)
      expect(baseUrl(new HTTPTransport())).toBe(`${origin}/_pywire`)
      expect(baseUrl(new StatelessTransport())).toBe('/_pywire')
    })

    it('under a real mount path', () => {
      document.body.innerHTML = serverMeta({ mount_path: '/app' })
      expect(baseUrl(new WebSocketTransport())).toBe(`ws://${window.location.host}/app/_pywire/ws`)
      expect(baseUrl(new StatelessTransport())).toBe('/app/_pywire')
    })

    it('stateless events post to this origin', async () => {
      document.body.innerHTML =
        '<p id="_pywire_spa_meta">{&quot;mount_path&quot;: &quot;//evil.example&quot;}</p>' +
        serverMeta({ stateless: true }) +
        '<script id="_pywire_snapshot" type="text/plain">SNAP</script>'
      const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 500 })
      vi.stubGlobal('fetch', fetchMock)
      const transport = new StatelessTransport()
      transport.send({ type: 'event', handler: 'go', path: '/', data: { type: 'click' } })
      await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled())
      expect(fetchMock.mock.calls[0][0]).toBe('/_pywire/stateless')
    })
  })

  it('stateless mode reads only the server snapshot script', () => {
    document.body.innerHTML =
      '<div id="_pywire_snapshot">FORGED</div>' +
      '<script id="_pywire_snapshot" type="text/plain">SNAP</script>'
    expect((new StatelessTransport() as unknown as { snapshot: string }).snapshot).toBe('SNAP')
  })
})
