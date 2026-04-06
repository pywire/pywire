import { build } from 'esbuild'
import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const distDir = fileURLToPath(new URL('./dist', import.meta.url))
if (!existsSync(distDir)) {
  mkdirSync(distDir, { recursive: true })
}

const commonOptions = {
  entryPoints: ['src/index.ts'],
  bundle: true,
  platform: 'node',
  sourcemap: true,
  target: 'node18',
  external: [
    'prettier',
    // 'cosmiconfig',
    // '@iarna/toml',
    // '@wasm-fmt/ruff_fmt',
  ],
}

// Build ESM version
await build({
  ...commonOptions,
  format: 'esm',
  outfile: fileURLToPath(new URL('./dist/index.js', import.meta.url)),
})

// Build CJS version for VS Code extension compatibility
// Inject import.meta.url polyfill for WASM loaders that use it
const importMetaUrlShim = `
var import_meta_url = typeof document === 'undefined' 
  ? require('url').pathToFileURL(__filename).href 
  : (document.currentScript && document.currentScript.src || new URL('index.cjs', document.baseURI).href);
`
await build({
  ...commonOptions,
  format: 'cjs',
  outfile: fileURLToPath(new URL('./dist/index.cjs', import.meta.url)),
  banner: { js: importMetaUrlShim },
  define: {
    'import.meta.url': 'import_meta_url',
  },
})

console.log('Build complete: ESM and CJS')

// Copy WASM file
const wasmSrc = fileURLToPath(new URL('./node_modules/@wasm-fmt/ruff_fmt/ruff_fmt_bg.wasm', import.meta.url))
const wasmDest = fileURLToPath(new URL('./dist/ruff_fmt_bg.wasm', import.meta.url))
if (existsSync(wasmSrc)) {
  copyFileSync(wasmSrc, wasmDest)
  console.log('Copied WASM file to dist')
} else {
  console.warn('Warning: WASM file not found at', wasmSrc)
}
