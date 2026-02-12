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
    // We specify dependencies/versions explicitly to match the docs runtime (Pyodide 0.29.x -> Emscripten 4.0.9)
    try {
      // 1. Clean up any stale build artifacts
      const staleXbuildenv = path.join(REPO_ROOT, '.pyodide-xbuildenv')
      if (fs.existsSync(staleXbuildenv)) {
        console.log(`Removing stale xbuildenv at ${staleXbuildenv}`)
        fs.rmSync(staleXbuildenv, { recursive: true, force: true })
      }

      const env = {
        ...process.env,
        PYODIDE_VERSION: '0.29.3',
        // Protect host builds from potential WASM-specific environment leakage
        EMCC_SKIP_WASM_OPT: '1',
        EM_IGNORE_WASM_OPT: '1',
      }
      delete env.VIRTUAL_ENV
      delete env.PYTHONPATH

      console.log('Building for Pyodide 0.29.3 with Emscripten 4.0.9')

      const venvPath = path.join(REPO_ROOT, '.build-venv')
      const pyodideBin = path.join(venvPath, 'bin', 'pyodide')
      const emsdkEnvPath = path.join(REPO_ROOT, 'emsdk', 'emsdk_env.sh')

      // Use Python 3.13 for the build environment (required for Pyodide 0.29.x + pyodide-build 0.32.0)
      const setupCmd = [
        `uv venv ${venvPath} --python 3.13`,
        `uv pip install --python ${venvPath}/bin/python "pyodide-build>=0.32.0" "wheel>=0.42.0" "pip"`,
      ].join(' && ')

      console.log('Setting up build environment (Python 3.13)...')
      run(setupCmd, REPO_ROOT)

      let buildCommand = `${pyodideBin} build . --verbose --exports whole_archive --outdir ${publicDistDir}`
      if (fs.existsSync(emsdkEnvPath)) {
        console.log(`Found local emsdk at ${emsdkEnvPath}, sourcing it...`)
        buildCommand = `bash -c "source '${emsdkEnvPath}' && ${buildCommand}"`
      }

      const pyodideRunCmd = `env RUSTUP_TOOLCHAIN=nightly ${buildCommand}`
      execSync(pyodideRunCmd, { cwd: REPO_ROOT, stdio: 'inherit', env })
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
