import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const DOCS_DIR = path.resolve(__dirname, '..')
const DOCS_PUBLIC_DIR = path.resolve(DOCS_DIR, 'public')
const PYWIRE_PKG = path.resolve(__dirname, '../../packages/pywire')
const PYWIRE_PARSER_PKG = path.resolve(__dirname, '../../packages/pywire-parser')
const TS_PYWIRE_PKG = path.resolve(__dirname, '../../packages/tree-sitter-pywire')
const CLIENT_DIR = path.resolve(PYWIRE_PKG, 'src/pywire/client')

// Use execFileSync (no shell) so paths with spaces/special chars are safe
function run(bin, args, cwd) {
  console.log(`> ${bin} ${args.join(' ')} (in ${cwd})`)
  execFileSync(bin, args, { cwd, stdio: 'inherit' })
}

const INSTALL_SOURCE = process.env.PYWIRE_PYPI_INSTALL === '1' ? 'pypi' : 'local'

function bundleWorkers({
  pywireWheel = 'unknown',
  parserWheel = 'unknown',
  tsPywireWheel = 'unknown',
} = {}) {
  console.log('\n--- Bundling Workers ---')
  const workers = [
    { src: 'src/sw.ts', dest: 'public/sw.js' },
    { src: 'src/pywire-worker.ts', dest: 'public/pywire-worker.js' },
  ]

  // Use JSON.stringify so each value is a valid JS string literal for esbuild --define.
  // Do NOT wrap in shell-style outer quotes ('"..."') — execFileSync passes args directly
  // to esbuild without shell processing, so the outer quotes would become part of the value.
  const defineArgs = [
    `--define:__PYWIRE_WHEEL_NAME__=${JSON.stringify(pywireWheel)}`,
    `--define:__PYWIRE_PARSER_WHEEL_NAME__=${JSON.stringify(parserWheel)}`,
    `--define:__TS_PYWIRE_WHEEL_NAME__=${JSON.stringify(tsPywireWheel)}`,
    `--define:__PYWIRE_INSTALL_SOURCE__=${JSON.stringify(INSTALL_SOURCE)}`,
  ]

  for (const worker of workers) {
    const swSrc = path.resolve(DOCS_DIR, worker.src)
    const swDest = path.resolve(DOCS_DIR, worker.dest)
    run(
      'npx',
      [
        'esbuild',
        swSrc,
        '--bundle',
        `--outfile=${swDest}`,
        '--minify',
        '--platform=browser',
        ...defineArgs,
      ],
      DOCS_DIR,
    )
  }
}

async function main() {
  console.log('Building Assets for Docs...')

  // 1. Build Client
  console.log('\n--- Building Client ---')
  if (!fs.existsSync(path.join(CLIENT_DIR, 'node_modules'))) {
    run('pnpm', ['install'], CLIENT_DIR)
  }
  run('pnpm', ['build'], CLIENT_DIR)

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

  // 2. Build Python Wheels (skipped in PyPI mode — packages come from PyPI at runtime)
  const publicDistDir = path.join(DOCS_PUBLIC_DIR, 'dist')

  if (INSTALL_SOURCE === 'pypi') {
    console.log(
      '\n--- PyPI mode: skipping wheel builds (packages installed from PyPI at runtime) ---',
    )
    fs.mkdirSync(publicDistDir, { recursive: true })
    bundleWorkers({
      pywireWheel: 'NOT_NEEDED',
      parserWheel: 'NOT_NEEDED',
      tsPywireWheel: 'NOT_NEEDED',
    })
    return
  }

  console.log('\n--- Building Python Wheels (local mode) ---')

  // Clean old wheels
  if (fs.existsSync(publicDistDir)) {
    console.log(`Cleaning ${publicDistDir}...`)
    const oldWheels = fs.readdirSync(publicDistDir).filter((f) => f.endsWith('.whl'))
    for (const old of oldWheels) {
      fs.unlinkSync(path.join(publicDistDir, old))
    }
  } else {
    fs.mkdirSync(publicDistDir, { recursive: true })
  }

  // 2a. Build pywire-parser (pure Python)
  console.log('\n--- Building pywire-parser wheel ---')
  run('uv', ['build', '--wheel', '--out-dir', publicDistDir], PYWIRE_PARSER_PKG)

  // 2b. Build tree-sitter-pywire
  // If PYWIRE_WASM_BUILD is set, use pyodide build for WASM wheel (CI with emsdk)
  // Otherwise, build a native wheel (local dev — will be mocked in the worker if not WASM-compatible)
  console.log('\n--- Building tree-sitter-pywire wheel ---')
  if (process.env.PYWIRE_WASM_BUILD === '1') {
    try {
      const baseEnv = { ...process.env }
      delete baseEnv.VIRTUAL_ENV
      delete baseEnv.PYTHONPATH

      // Set up a build venv with pyodide-cli (provides `pyodide` command)
      const venvPath = path.join(TS_PYWIRE_PKG, '.build-venv')
      const pyodideBin = path.join(venvPath, 'bin', 'pyodide')
      run('uv', ['venv', venvPath, '--python', '3.13'], TS_PYWIRE_PKG)
      run(
        'uv',
        ['pip', 'install', '--python', path.join(venvPath, 'bin', 'python'), 'pyodide-cli', 'pip'],
        TS_PYWIRE_PKG,
      )

      // Set up the Pyodide cross-build environment for the target version
      run(pyodideBin, ['xbuildenv', 'install', '0.29.3'], TS_PYWIRE_PKG)

      // Ask pyodide-build which Emscripten version is required — avoids hardcoding
      const { execFileSync: execSync } = await import('node:child_process')
      const emscriptenVersion = execSync(pyodideBin, ['config', 'get', 'emscripten_version'], {
        cwd: TS_PYWIRE_PKG,
        env: baseEnv,
      })
        .toString()
        .trim()
      console.log(`Required Emscripten version: ${emscriptenVersion}`)

      // Locate or install emsdk: prefer existing activated env, then EMSDK_ENV_PATH, then clone
      let emsdkEnvPath = ''
      const emsdkCandidates = [
        process.env.EMSDK ? path.join(process.env.EMSDK, 'emsdk_env.sh') : null,
        process.env.EMSDK_ENV_PATH,
        path.join(TS_PYWIRE_PKG, 'emsdk', 'emsdk_env.sh'),
        path.join(PYWIRE_PKG, 'emsdk', 'emsdk_env.sh'),
      ].filter(Boolean)
      emsdkEnvPath = emsdkCandidates.find((p) => fs.existsSync(p)) || ''

      if (!emsdkEnvPath) {
        console.log('emsdk not found locally — cloning and installing...')
        const emsdkDir = path.join(TS_PYWIRE_PKG, 'emsdk')
        run(
          'git',
          ['clone', 'https://github.com/emscripten-core/emsdk.git', emsdkDir],
          TS_PYWIRE_PKG,
        )
        run('./emsdk', ['install', emscriptenVersion], emsdkDir)
        run('./emsdk', ['activate', emscriptenVersion], emsdkDir)
        emsdkEnvPath = path.join(emsdkDir, 'emsdk_env.sh')
      }

      console.log(`Using emsdk from: ${emsdkEnvPath}`)
      const buildEnv = {
        ...baseEnv,
        EMCC_SKIP_WASM_OPT: '1',
        EM_IGNORE_WASM_OPT: '1',
      }
      // Source emsdk_env.sh then run pyodide build. Pass all paths as positional args
      // to avoid shell interpolation of env-derived values ($1, $2, $3 are not interpolated).
      execFileSync(
        'bash',
        [
          '-c',
          'source "$1" && "$2" build . --verbose --outdir "$3"',
          '--',
          emsdkEnvPath,
          pyodideBin,
          publicDistDir,
        ],
        { cwd: TS_PYWIRE_PKG, stdio: 'inherit', env: buildEnv },
      )
    } catch (e) {
      console.error('Failed to build WASM wheel for tree-sitter-pywire:', e)
      process.exit(1)
    }
  } else {
    // Local dev: build native wheel — the worker will load tree-sitter from Pyodide's
    // built-in packages and mock tree-sitter-pywire if the wheel is not WASM-compatible
    try {
      run('uv', ['build', '--wheel', '--out-dir', publicDistDir], TS_PYWIRE_PKG)
    } catch (e) {
      console.warn(
        'tree-sitter-pywire native build failed (expected in some environments):',
        e.message,
      )
    }
  }

  // 2c. Build pywire (pure Python)
  console.log('\n--- Building pywire wheel ---')
  try {
    run('uv', ['build', '--wheel', '--out-dir', publicDistDir], PYWIRE_PKG)
  } catch (_e) {
    console.warn('uv build failed, trying uv run python -m build')
    try {
      run(
        'uv',
        ['run', '--all-extras', 'python', '-m', 'build', '--wheel', '--outdir', publicDistDir],
        PYWIRE_PKG,
      )
    } catch (_e2) {
      console.warn('uv run failed, falling back to .venv/bin/python3')
      run(
        path.join(PYWIRE_PKG, '.venv', 'bin', 'python3'),
        ['-m', 'build', '--wheel', '--outdir', publicDistDir],
        PYWIRE_PKG,
      )
    }
  }

  // Rename all wheels with a shared timestamp to bust HTTP + service worker caches.
  // The worker's INSTALLED_MARKER cache key is built from all three filenames,
  // so any rename also invalidates the IDBFS package cache.
  const timestamp = new Date().getTime()

  function findAndTimestampWheel(prefix) {
    const allFiles = fs.readdirSync(publicDistDir)
    const match = allFiles
      .filter((f) => f.startsWith(prefix) && f.endsWith('.whl'))
      .sort()
      .pop() // newest by name (version sorts lexically)
    if (!match) return null
    const stamped = match.replace('.whl', `.${timestamp}.whl`)
    fs.renameSync(path.join(publicDistDir, match), path.join(publicDistDir, stamped))
    console.log(`Renamed ${match} → ${stamped}`)
    return stamped
  }

  const pywireWheel = findAndTimestampWheel('pywire-')
  const parserWheel = findAndTimestampWheel('pywire_parser-')
  const tsPywireWheel = findAndTimestampWheel('tree_sitter_pywire-')

  if (!pywireWheel) {
    console.error('No pywire wheel file generated!')
    process.exit(1)
  }
  if (!parserWheel) {
    console.error('No pywire-parser wheel found!')
    process.exit(1)
  }

  const allWheels = fs.readdirSync(publicDistDir).filter((f) => f.endsWith('.whl'))
  console.log('\nAll wheels in dist:')
  for (const f of allWheels) {
    console.log(`  ${f}`)
  }

  // 3. Bundle Workers (inject all wheel filenames)
  bundleWorkers({
    pywireWheel,
    parserWheel,
    tsPywireWheel: tsPywireWheel || 'NOT_BUILT',
  })
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
