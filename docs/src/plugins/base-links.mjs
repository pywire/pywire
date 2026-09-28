// @ts-check
import { posix } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Sätteri mdast plugin that normalizes internal links in docs content so they
 * survive the pywire.dev proxy, which serves the Cloudflare Pages project
 * under `/docs`.
 *
 * - Root-relative links (`/guides/x`) get the site `base` prepended when missing.
 * - Relative links (`./x/`, `../guides/y/`) resolve against the source file's
 *   directory under `src/content/docs`, not the rendered page URL.
 * - Page links get a trailing slash. Without it, Pages answers with a 308 to
 *   `/guides/x/`, a path that has lost `/docs` and 404s on pywire.dev.
 *
 * @param {{ base: string }} options
 */
export default function baseLinks({ base }) {
  const prefix = base.replace(/\/+$/, '')
  const contentDir = '/src/content/docs/'

  /**
   * @param {string} url
   * @param {string | undefined} filePath
   */
  function normalize(url, filePath) {
    const [, rawPath = '', suffix = ''] = url.match(/^([^?#]*)(.*)$/s) ?? []
    let path = rawPath
    if (path.startsWith('./') || path.startsWith('../')) {
      const at = filePath?.lastIndexOf(contentDir) ?? -1
      if (!filePath || at === -1) return url
      const dir = posix.dirname(filePath.slice(at + contentDir.length))
      path = posix.join('/', dir, path)
    } else if (!path.startsWith('/') || path.startsWith('//')) {
      return url
    }
    if (path !== prefix && !path.startsWith(`${prefix}/`)) path = prefix + path
    const lastSegment = path.slice(path.lastIndexOf('/') + 1)
    if (lastSegment && !lastSegment.includes('.')) path += '/'
    return path + suffix
  }

  /** @param {{ fileURL?: URL }} ctx */
  return ({ fileURL }) => {
    const filePath = fileURL && fileURLToPath(fileURL).replaceAll('\\', '/')
    /** @type {(node: { url: string }, ctx: any) => void} */
    const visit = (node, ctx) => {
      const url = normalize(node.url, filePath)
      if (url !== node.url) ctx.setProperty(node, 'url', url)
    }
    return { name: 'pywire-base-links', link: visit, definition: visit }
  }
}
