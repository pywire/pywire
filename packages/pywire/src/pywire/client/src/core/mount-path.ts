/**
 * Read the ASGI mount prefix from the SPA metadata script injected by the
 * server. Empty string when PyWire is mounted at "/".
 *
 * The meta tag is inlined into the HTML shell before the client bundle
 * executes, so this is always safe to call synchronously at module load
 * or inside transport constructors.
 */
export function getMountPath(): string {
  const el = document.getElementById('_pywire_spa_meta')
  if (!el) return ''
  try {
    const parsed = JSON.parse(el.textContent || '{}')
    if (typeof parsed.mount_path === 'string') return parsed.mount_path
  } catch {
    /* meta missing or malformed → behave as if unmounted */
  }
  return ''
}
