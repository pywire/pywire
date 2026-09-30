/**
 * The client's server-rendered config: `<script id="_pywire_spa_meta"
 * type="application/json">`, which the server writes right before the client
 * bundle's own `<script>` at the end of `<body>`.
 *
 * Page markup can carry the same id (a user-chosen anchor, say), so only a
 * JSON `<script>` counts, and the config the page booted with is read once:
 * later DOM changes never move the transports' URLs.
 */

export type SpaMeta = Readonly<Record<string, unknown>>

const META_ID = '_pywire_spa_meta'

// The bundle's own <script>, captured while it executes: the server puts the
// meta element right before it.
const bootScript: Element | null = typeof document !== 'undefined' ? document.currentScript : null

let booted: SpaMeta | null = null

function isMetaScript(el: Element | null | undefined): el is HTMLScriptElement {
  return (
    !!el &&
    el.tagName === 'SCRIPT' &&
    el.id === META_ID &&
    (el.getAttribute('type') ?? '').trim().toLowerCase() === 'application/json'
  )
}

/**
 * The meta script under `root`. The server appends it after all page markup,
 * so the last JSON script with the id is the server's.
 */
export function findSpaMetaScript(root: ParentNode = document): HTMLScriptElement | null {
  const found = Array.from(root.querySelectorAll(`script#${META_ID}`)).filter(isMetaScript)
  return found.length ? found[found.length - 1] : null
}

/** The JSON object in a meta script, or null when it holds anything else. */
export function parseSpaMeta(el: HTMLScriptElement | null): SpaMeta | null {
  if (!el) return null
  try {
    const parsed: unknown = JSON.parse(el.textContent || '')
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return Object.freeze({ ...(parsed as Record<string, unknown>) })
    }
  } catch {
    /* malformed → no config */
  }
  return null
}

/** The config this page booted with, read once. Empty when there is none. */
export function bootSpaMeta(): SpaMeta {
  if (booted === null) {
    const previous = bootScript?.previousElementSibling
    booted = parseSpaMeta(isMetaScript(previous) ? previous : findSpaMetaScript()) ?? {}
  }
  return booted
}

/** Forget the boot config, so the next read takes it from the document again. For tests. */
export function resetSpaMeta(): void {
  booted = null
}

/**
 * A path on this origin: one leading `/` (not `//` or `/\`, which browsers
 * resolve to another host), no backslashes, no control characters.
 */
export function isSameOriginPath(value: unknown): value is string {
  if (typeof value !== 'string' || !value.startsWith('/')) return false
  if (value.startsWith('//') || value.includes('\\')) return false
  for (let i = 0; i < value.length; i++) {
    const code = value.charCodeAt(i)
    if (code < 0x21 || code === 0x7f) return false
  }
  return true
}

/**
 * A URL prefix the app is mounted under: empty, or `/`-separated non-empty
 * segments of URL path characters (`/app`, `/team/app`).
 */
export function isMountPath(value: unknown): value is string {
  return typeof value === 'string' && /^(?:\/[\w\-.~!$&'()*+,;=:@%]+)*$/.test(value)
}

/**
 * The ASGI mount prefix every framework URL starts with. Empty when PyWire is
 * mounted at "/", or when the boot config carries anything but a mount path.
 */
export function getMountPath(): string {
  const mount = bootSpaMeta().mount_path
  return isMountPath(mount) ? mount : ''
}
