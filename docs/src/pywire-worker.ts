/* global loadPyodide, __PYWIRE_WHEEL_NAME__, __PYWIRE_PARSER_WHEEL_NAME__, __TS_PYWIRE_WHEEL_NAME__, __PYWIRE_INSTALL_SOURCE__ */
/// <reference lib="webworker" />

// Import type-only since we use importScripts for the actual library
import type { PyodideInterface } from 'pyodide'

declare global {
  function loadPyodide(options?: any): Promise<PyodideInterface>
  function importScripts(...urls: string[]): void
  /** Injected at build time via esbuild --define */
  const __PYWIRE_WHEEL_NAME__: string
  const __PYWIRE_PARSER_WHEEL_NAME__: string
  const __TS_PYWIRE_WHEEL_NAME__: string
  /** 'pypi' = install from PyPI at runtime, 'local' = install from /dist/ wheels */
  const __PYWIRE_INSTALL_SOURCE__: string
}

importScripts('https://cdn.jsdelivr.net/pyodide/v0.29.3/full/pyodide.js')

let pyodide: PyodideInterface | null = null

async function loadPywire(baseUrl: string) {
  console.log('[Worker] Starting loadPywire with baseUrl:', baseUrl)
  postMessage({ type: 'STDOUT', message: 'Loading Pyodide runtime...' })

  pyodide = await loadPyodide()
  console.log('[Worker] Pyodide loaded successfully')

  // Mount IDBFS for persistent packages
  const PERSISTENT_DIR = '/home/pyodide/persistent'
  try {
    // Ensure path exists
    const parts = PERSISTENT_DIR.split('/').filter(Boolean)
    let currentPath = ''
    for (const part of parts) {
      currentPath += `/${part}`
      try {
        if (!pyodide.FS.analyzePath(currentPath).exists) {
          pyodide.FS.mkdir(currentPath)
        }
      } catch (_e) {
        // Ignore if it exists (Errno 17) or other minor errors
      }
    }

    pyodide.FS.mount((pyodide.FS as any).filesystems.IDBFS, {}, PERSISTENT_DIR)
    console.log('[Worker] IDBFS mounted')

    // Sync from IndexedDB to memory
    await new Promise<void>((resolve, reject) => {
      pyodide!.FS.syncfs(true, (err: any) => {
        if (err) {
          console.error('[Worker] Error syncing IDBFS (read):', err)
          reject(err)
        } else {
          console.log('[Worker] IDBFS synced from IndexedDB')
          resolve()
        }
      })
    })
  } catch (e) {
    console.error('[Worker] Failed to mount IDBFS:', e)
  }

  postMessage({ type: 'STDOUT', message: 'Pyodide loaded. Checking cache...' })

  try {
    // Add persistent path to sys.path immediately
    const sitePackages = `${PERSISTENT_DIR}/site-packages`
    await pyodide.runPythonAsync(`
import sys, os, importlib
PERSISTENT_SITE_PACKAGES = "${sitePackages}"
print(f"[Python] Checking {PERSISTENT_SITE_PACKAGES}...")
if not os.path.exists(PERSISTENT_SITE_PACKAGES):
    os.makedirs(PERSISTENT_SITE_PACKAGES, exist_ok=True)
    print(f"[Python] Created {PERSISTENT_SITE_PACKAGES}")
if PERSISTENT_SITE_PACKAGES not in sys.path:
    sys.path.insert(0, PERSISTENT_SITE_PACKAGES)
    print(f"[Python] Inserted into sys.path: {PERSISTENT_SITE_PACKAGES}")
importlib.invalidate_caches()
`)

    // Cache validation — key format depends on install source
    const markerFile = `${PERSISTENT_DIR}/INSTALLED_MARKER`
    let cacheKey: string

    if (__PYWIRE_INSTALL_SOURCE__ === 'local') {
      cacheKey = `local|${[__PYWIRE_WHEEL_NAME__, __PYWIRE_PARSER_WHEEL_NAME__, __TS_PYWIRE_WHEEL_NAME__].join('|')}`
    } else {
      // PyPI mode: cache key is checked after install (based on installed versions)
      cacheKey = ''
    }

    // Escape for safe interpolation into Python string literals
    const safeCacheKey = cacheKey.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
    const safeMarkerFile = markerFile.replace(/\\/g, '\\\\').replace(/"/g, '\\"')

    const checkResult = await pyodide.runPythonAsync(`
import os, sys, importlib
cache_valid = False
marker_path = "${safeMarkerFile}"
expected_key = "${safeCacheKey}"
if expected_key and os.path.exists(marker_path):
    stored_key = open(marker_path).read().strip()
    if stored_key == expected_key:
        try:
            import pywire
            from pywire_parser.ts_parser import PYWIRE_LANGUAGE
            cache_valid = True
            print("[Python] Cache validated: all packages importable")
        except Exception as e:
            print(f"[Python] Cache invalid, import failed: {e}")
    else:
        print(f"[Python] Cache key mismatch, will reinstall")
else:
    print("[Python] No cache marker found or PyPI mode (will check versions)")
cache_valid
`)

    if (checkResult) {
      console.log('[Worker] Packages found and verified in IDBFS cache. Skipping installation.')
      postMessage({ type: 'STDOUT', message: 'Packages loaded from cache.' })
    } else {
      console.log('[Worker] Installing packages...')
      postMessage({ type: 'STDOUT', message: 'Installing packages...' })

      // Load core packages from Pyodide's built-in index
      await pyodide.loadPackage(['micropip', 'ssl', 'pydantic', 'anyio', 'tree-sitter'])
      console.log('[Worker] Core packages loaded (including tree-sitter)')

      const micropip = pyodide.pyimport('micropip')

      // Mock CLI-only dependencies that aren't available in Pyodide
      micropip.add_mock_package('watchfiles', '0.21.0')
      micropip.add_mock_package('uvicorn', '0.27.0')
      micropip.add_mock_package('textual', '7.4.0')
      micropip.add_mock_package('rich-click', '1.9.6')

      if (__PYWIRE_INSTALL_SOURCE__ === 'pypi') {
        // ── PyPI mode ──────────────────────────────────────────────
        // Pure-Python packages come from PyPI; tree-sitter-pywire is a C extension
        // compiled for Pyodide (WASM) and served from the PyWire CDN simple index.
        console.log('[Worker] PyPI mode: installing pywire from PyPI...')
        postMessage({ type: 'STDOUT', message: 'Installing from PyPI...' })

        // Add PyWire CDN as a package index alongside PyPI. The CDN hosts the
        // tree-sitter-pywire WASM wheel (not on PyPI). Packages not on the CDN
        // return 404, so micropip falls through to PyPI automatically.
        await pyodide.runPythonAsync(
          'import micropip; micropip.set_index_urls(["https://pywire.dev/cdn/simple", "https://pypi.org/simple"])',
        )
        await micropip.install('typing-extensions>=4.10.0', { target: sitePackages })
        await micropip.install('starlette', { target: sitePackages })
        await micropip.install('tree-sitter-pywire', { target: sitePackages })
        await micropip.install('pywire-parser', { target: sitePackages })
        await micropip.install('pywire', { target: sitePackages, deps: false })
        console.log('[Worker] All packages installed from PyPI')

        // Build cache key from actual installed versions
        cacheKey = await pyodide.runPythonAsync(`
import importlib.metadata
versions = []
for pkg in ['pywire', 'pywire-parser', 'tree-sitter-pywire']:
    try:
        versions.append(f"{pkg}=={importlib.metadata.version(pkg)}")
    except Exception:
        versions.append(f"{pkg}==unknown")
"pypi|" + "|".join(versions)
`)
      } else {
        // ── Local mode ─────────────────────────────────────────────
        // Install from /dist/ wheels built at build time
        await micropip.install('typing-extensions>=4.10.0', { target: sitePackages })
        await micropip.install('starlette', { target: sitePackages })
        console.log('[Worker] Base dependencies installed')

        async function installLocalWheel(wheelName: string, label: string) {
          const url = `${baseUrl}dist/${wheelName}`
          console.log(`[Worker] Installing ${label} from: ${url}`)
          const resp = await fetch(url)
          if (!resp.ok) throw new Error(`Failed to fetch ${url}: ${resp.status}`)
          const buf = await resp.arrayBuffer()
          pyodide!.FS.writeFile(`/${wheelName}`, new Uint8Array(buf))
          await micropip.install(`emfs:/${wheelName}`, { target: sitePackages, deps: false })
          console.log(`[Worker] ${label} installed`)
        }

        await installLocalWheel(__TS_PYWIRE_WHEEL_NAME__, 'tree-sitter-pywire')
        await installLocalWheel(__PYWIRE_PARSER_WHEEL_NAME__, 'pywire-parser')
        await installLocalWheel(__PYWIRE_WHEEL_NAME__, 'pywire')
      }

      // Write cache marker
      pyodide.FS.writeFile(`${PERSISTENT_DIR}/INSTALLED_MARKER`, cacheKey)

      // Sync to IndexedDB
      await new Promise<void>((resolve, reject) => {
        pyodide!.FS.syncfs(false, (err: any) => {
          if (err) {
            console.error('[Worker] Error syncing IDBFS (write):', err)
            reject(err)
          } else {
            console.log('[Worker] IDBFS synced to IndexedDB')
            resolve()
          }
        })
      })

      await pyodide.runPythonAsync('import importlib; importlib.invalidate_caches()')
      postMessage({ type: 'STDOUT', message: 'Packages installed and cached.' })
    }

    postMessage({ type: 'STDOUT', message: 'PyWire ready.' })

    // Extract bundled client JS from the installed pywire package so the
    // preview iframe can load them without a separate static-file copy step.
    console.log('[Worker] Extracting bundled client JS from pywire package...')
    const staticFilesJson = await pyodide.runPythonAsync(`
import importlib.resources, json
_files = {}
for _name in ['pywire.core.min.js', 'pywire.dev.min.js']:
    try:
        _files[_name] = importlib.resources.files("pywire.static").joinpath(_name).read_text()
    except Exception as _e:
        print(f"[Python] Failed to read {_name}: {_e}")
json.dumps(_files)
`)
    const staticFiles: Record<string, string> = JSON.parse(staticFilesJson)
    console.log(
      '[Worker] Extracted static files:',
      Object.keys(staticFiles).map((k) => `${k} (${staticFiles[k].length} chars)`),
    )
    postMessage({ type: 'STATIC_FILES', files: staticFiles })

    // Initialize File System
    if (!pyodide.FS.analyzePath('/app').exists) {
      pyodide.FS.mkdir('/app')
    }
    console.log('[Worker] /app directory created')

    // Load the Shim
    console.log('[Worker] Fetching shim.py from:', `${baseUrl}shim.py`)
    const shimCode = await fetch(`${baseUrl}shim.py`).then((r) => r.text())
    console.log('[Worker] Running shim.py...')
    postMessage({ type: 'STDOUT', message: 'Initializing PyWire shim...' })
    await pyodide.runPythonAsync(shimCode)
    console.log('[Worker] Shim executed successfully')

    postMessage({ type: 'STDOUT', message: '\x1b[32mReady!\x1b[0m' })
    postMessage({ type: 'READY' })
    console.log('[Worker] READY message sent')
  } catch (_e: any) {
    console.error('[Worker] Error:', _e)
    postMessage({ type: 'STDERR', message: `Worker Initialization Failed: ${_e}` })
  }
}

self.onmessage = async (event) => {
  const { type, payload } = event.data

  if (!pyodide && type !== 'INIT') return

  if (type === 'INIT') {
    const baseUrl = payload.baseUrl || '/'
    await loadPywire(baseUrl)
  } else if (type === 'UPDATE_FILE') {
    // Write user code to virtual FS
    const path = `/app/${payload.filename}`
    console.log('[Worker] UPDATE_FILE:', path)

    // Ensure parent directory exists
    const dir = path.substring(0, path.lastIndexOf('/'))
    const parts = dir.split('/').filter(Boolean)
    let current = ''
    for (const part of parts) {
      current += `/${part}`
      if (!pyodide!.FS.analyzePath(current).exists) {
        pyodide!.FS.mkdir(current)
      }
    }

    pyodide!.FS.writeFile(path, payload.content)

    // Invalidate app cache for this file
    try {
      const result = pyodide!.globals.get('reload_page')(path)
      console.log('[Worker] reload_page result:', result)
    } catch (e) {
      console.error('[Worker] reload_page FAILED:', e)
    }
  } else if (type === 'RESTART') {
    console.log('[Worker] Restarting pywire server...')
    const { pagesDir } = payload || {}

    function recursiveDelete(dir: string) {
      if (!pyodide!.FS.analyzePath(dir).exists) return
      const entries = pyodide!.FS.readdir(dir)
      for (const entry of entries) {
        if (entry === '.' || entry === '..') continue
        const fullPath = `${dir}/${entry}`
        const stat = pyodide!.FS.stat(fullPath)
        if (pyodide!.FS.isDir(stat.mode)) {
          recursiveDelete(fullPath)
          pyodide!.FS.rmdir(fullPath)
        } else {
          pyodide!.FS.unlink(fullPath)
        }
      }
    }

    try {
      recursiveDelete('/app')

      // Re-initialize app cache in shim
      // Pass the new pagesDir to the shim
      const fullPagesDir = pagesDir ? `/app/${pagesDir}` : '/app'
      pyodide!.globals.get('restart_server')(fullPagesDir)
      console.log('[Worker] Server restart successful, fullPagesDir:', fullPagesDir)
    } catch (e) {
      console.error('[Worker] Error during restart:', e)
    }
  } else if (type === 'REQUEST') {
    // Pass to Python shim safely
    console.log('[Worker] REQUEST:', payload.type, payload.path || payload.id || '')
    pyodide!.globals.set('temp_req_payload', pyodide!.toPy(payload))
    await pyodide!.runPythonAsync(`
import asyncio
import js
from pyodide.ffi import to_js
asyncio.create_task(js.handle_message(temp_req_payload))
    `)
  }
}
