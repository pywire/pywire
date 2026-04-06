import * as ruffModule from '@wasm-fmt/ruff_fmt'

type RuffModule = typeof ruffModule & {
  default?: (input?: ArrayBuffer | Buffer) => Promise<void>
  format?: (code: string, filename: string | undefined, options: Record<string, unknown>) => string
}

let initPromise: Promise<void> | null = null
let isInitialized = false

export function initializeRuff(): Promise<void> {
  if (initPromise) return initPromise

  initPromise = (async () => {
    const module = ruffModule as RuffModule
    const initFn = module.default

    if (typeof initFn === 'function') {
      try {
        // In Node, try loading the wasm file explicitly if we can
        let wasmBuffer: Buffer | undefined
        if (typeof process !== 'undefined' && process.versions && process.versions.node) {
          try {
            const fs = await import('fs')
            const path = await import('path')
            const { fileURLToPath } = await import('url')

            let currentDir: string
            if (typeof __dirname !== 'undefined') {
              currentDir = __dirname
            } else {
              currentDir = path.dirname(fileURLToPath(import.meta.url))
            }

            const wasmPath = path.join(currentDir, 'ruff_fmt_bg.wasm')
            if (fs.existsSync(wasmPath)) {
              wasmBuffer = fs.readFileSync(wasmPath)
            }
          } catch {
            // Fallback to fetch
          }
        }

        await initFn(wasmBuffer)
        isInitialized = true
        // console.error('[PyWire] Ruff WASM initialized')
      } catch (e) {
        if (typeof process !== 'undefined' && process.stderr) {
          process.stderr.write(`[PyWire] Failed to initialize Ruff WASM: ${e}\n`)
        }
      }
    } else {
      isInitialized = true
    }
  })()

  return initPromise
}

export function formatPython(code: string, options: Record<string, unknown>): string {
  if (!isInitialized) {
    if (typeof process !== 'undefined' && process.stderr) {
      process.stderr.write('[PyWire] Skip format: Ruff not initialized\n')
    }
    return code
  }

  const formatter = (ruffModule as RuffModule).format

  if (typeof formatter !== 'function') {
    return code
  }

  try {
    // console.error('[PyWire] Formatting python block...')
    const result = formatter(code, undefined, options)
    // console.error('[PyWire] Formatted success')
    return result
  } catch (e) {
    if (typeof process !== 'undefined' && process.stderr) {
      process.stderr.write(`[PyWire] Ruff format error: ${e}\n`)
    }
    return code
  }
}
