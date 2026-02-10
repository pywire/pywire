import { execSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(__dirname, '../..')
const DOCS_DIR = path.resolve(__dirname, '..')
const DOCS_PUBLIC_DIR = path.resolve(DOCS_DIR, 'public')
const CLIENT_DIR = path.resolve(REPO_ROOT, 'src/pywire/client')

function run(cmd, cwd) {
  console.log(`> ${cmd} (in ${cwd})`)
  execSync(cmd, { cwd, stdio: 'inherit' })
}

function bundleWorkers(wheelFile = 'unknown') {
  console.log('\n--- Bundling Workers ---')
  const workers = [
    { src: 'src/sw.ts', dest: 'public/sw.js' },
    { src: 'src/pywire-worker.ts', dest: 'public/pywire-worker.js' },
  ]

  for (const worker of workers) {
    const swSrc = path.resolve(DOCS_DIR, worker.src)
    const swDest = path.resolve(DOCS_DIR, worker.dest)
    const define = `--define:__PYWIRE_WHEEL_NAME__='"${wheelFile}"'`
    run(
      `npx esbuild ${swSrc} --bundle --outfile=${swDest} --minify --platform=browser ${define}`,
      DOCS_DIR,
    )
  }
}

async function main() {
  console.log('Building Assets for Docs...')

  // 1. Build Client
  console.log('\n--- Building Client ---')
  // Ensure we have deps
  if (!fs.existsSync(path.join(CLIENT_DIR, 'node_modules'))) {
    run('pnpm install', CLIENT_DIR)
  }
  run('pnpm build', CLIENT_DIR)

  // Copy built client files
  const staticDest = path.join(DOCS_PUBLIC_DIR, '_pywire/static')
  fs.mkdirSync(staticDest, { recursive: true })

  const clientSrcDir = path.resolve(CLIENT_DIR, '../static')
  if (fs.existsSync(clientSrcDir)) {
    const files = fs.readdirSync(clientSrcDir)
    for (const file of files) {
      if (file.endsWith('.js') || file.endsWith('.js.map')) {
        console.log(`Copying ${file} to ${staticDest}`)
        fs.copyFileSync(path.join(clientSrcDir, file), path.join(staticDest, file))
      }
    }
  } else {
    console.error(`Client build directory not found: ${clientSrcDir}`)
    process.exit(1)
  }

  // 2. Build Python Wheel
  console.log('\n--- Building Python Wheel ---')
  const publicDistDir = path.join(DOCS_PUBLIC_DIR, 'dist')

  // Clean old wheels in public/dist
  if (fs.existsSync(publicDistDir)) {
    console.log(`Cleaning ${publicDistDir}...`)
    const oldWheels = fs.readdirSync(publicDistDir).filter((f) => f.endsWith('.whl'))
    for (const old of oldWheels) {
      fs.unlinkSync(path.join(publicDistDir, old))
    }
  } else {
    fs.mkdirSync(publicDistDir, { recursive: true })
  }

  // Build directly to public/dist
  // If PYWIRE_WASM_BUILD is set, use pyodide build for WASM wheel (requires Emscripten enviroment)
  // Otherwise, use standard uv build for native wheel (default)
  if (process.env.PYWIRE_WASM_BUILD === '1') {
    // Build directly to public/dist using pyodide build via uv
    // We specify dependencies/versions explicitly to match the docs runtime (Pyodide 0.29.x -> Emscripten 3.1.58)
    try {
      // Requires python >= 3.12 for pyodide-build 0.29.3
      // Requires wheel < 0.40.0 for auditwheel-emscripten compatibility
      // Requires prerelease=allow for pyodide-lock 0.1.0a7 dependency
      const pyodideCmd = `uv run --prerelease=allow --python 3.12 --with "pyodide-build==0.29.3" --with "wheel<0.40.0" --with pip pyodide build --outdir ${publicDistDir}`

      // Explicitly disable bulk-memory to satisfy Emscripten 3.1.58's wasm-opt
      // And skip wasm-opt entirely because 3.1.58's wasm-opt fails on modern flags
      const targetRustFlags = (process.env.RUSTFLAGS || '') + ' -C target-feature=-bulk-memory -C link-arg=-sWASM_OPT=0'
      const env = {
        ...process.env,
        CARGO_TARGET_WASM32_UNKNOWN_EMSCRIPTEN_RUSTFLAGS: targetRustFlags,
        EMCC_CFLAGS: (process.env.EMCC_CFLAGS || '') + ' -mno-bulk-memory',
        EMCC_CXXFLAGS: (process.env.EMCC_CXXFLAGS || '') + ' -mno-bulk-memory',
        EMCC_SKIP_WASM_OPT: '1',
        EM_IGNORE_WASM_OPT: '1'
      }
      delete env.RUSTFLAGS // Ensure RUSTFLAGS doesn't override target-specific flags or leak to host
      delete env.CFLAGS // Ensure CFLAGS doesn't leak to host
      delete env.CXXFLAGS // Ensure CXXFLAGS doesn't leak to host
      console.log('Building with target RUSTFLAGS:', targetRustFlags)
      console.log('Skipping wasm-opt (EMCC_SKIP_WASM_OPT=1)')

      execSync(pyodideCmd, { cwd: REPO_ROOT, stdio: 'inherit', env })
    } catch (e) {
      console.error('Failed to build WASM wheel:', e)
      process.exit(1)
    }
  } else {
    // Standard native build (default)
    try {
      run(`uv build --wheel --out-dir ${publicDistDir}`, REPO_ROOT)
    } catch (_e) {
      console.warn('uv build failed, trying uv run python -m build')
      try {
        run(`uv run --all-extras python -m build --wheel --outdir ${publicDistDir}`, REPO_ROOT)
      } catch (_e2) {
        console.warn('uv run failed, falling back to .venv/bin/python3')
        run(`.venv/bin/python3 -m build --wheel --outdir ${publicDistDir}`, REPO_ROOT)
      }
    }
  }

  // Find the wheel
  const distFiles = fs.readdirSync(publicDistDir)
  const wheelFiles = distFiles
    .filter((f) => f.endsWith('.whl'))
    .map((f) => ({ name: f, time: fs.statSync(path.join(publicDistDir, f)).mtime.getTime() }))
    .sort((a, b) => b.time - a.time)

  const wheelFile = wheelFiles.length > 0 ? wheelFiles[0].name : null

  if (!wheelFile) {
    console.error('No wheel file generated!')
    process.exit(1)
  }

  // Rename wheel to include timestamp to bust cache
  const timestamp = new Date().getTime()
  const newWheelName = wheelFile.replace('.whl', `.${timestamp}.whl`)
  const oldPath = path.join(publicDistDir, wheelFile)
  const newPath = path.join(publicDistDir, newWheelName)

  fs.renameSync(oldPath, newPath)
  console.log(`Renamed wheel to: ${newWheelName}`)

  console.log(`Generated wheel: ${newWheelName}`)

  // 3. Bundle Workers (now that we have the wheel filename)
  bundleWorkers(newWheelName)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
