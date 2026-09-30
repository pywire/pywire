#!/usr/bin/env node
// `npx create-pywire-app` / `npm create pywire-app`: the scaffolder is Python,
// so run it through uv (which also brings Python and pywire), installing uv
// first when it is missing. Arguments pass straight through.
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { homedir } from 'node:os'
import { delimiter, dirname, join } from 'node:path'

const isWindows = process.platform === 'win32'
const UV_DOCS = 'https://docs.astral.sh/uv/getting-started/installation/'
// The installer of one uv release, not whatever install.sh serves today; it
// checks the downloaded uv against that release's checksums.
const UV_INSTALLER = 'https://astral.sh/uv/0.12.21/install'

function findUv() {
  if (spawnSync('uv', ['--version'], { stdio: 'ignore' }).status === 0) return 'uv'
  // A fresh install is not on this process's PATH yet; look where uv puts it.
  const exe = isWindows ? 'uv.exe' : 'uv'
  const dirs = [process.env.XDG_BIN_HOME, join(homedir(), '.local', 'bin'), join(homedir(), '.cargo', 'bin')]
  for (const dir of dirs) {
    if (dir && existsSync(join(dir, exe))) return join(dir, exe)
  }
  return null
}

function installUv() {
  console.log('==> uv is not installed. Installing uv...')
  const [cmd, args] = isWindows
    ? ['powershell', ['-ExecutionPolicy', 'ByPass', '-NoProfile', '-c', `irm ${UV_INSTALLER}.ps1 | iex`]]
    : [
        'sh',
        [
          '-c',
          `if command -v curl >/dev/null 2>&1; then curl -LsSf ${UV_INSTALLER}.sh | sh; ` +
            `else wget -qO- ${UV_INSTALLER}.sh | sh; fi`,
        ],
      ]
  spawnSync(cmd, args, { stdio: ['ignore', 'inherit', 'inherit'] })
}

let uv = findUv()
const freshUv = uv === null
if (freshUv) {
  installUv()
  uv = findUv()
  if (uv === null) {
    console.error(`Error: could not install uv. Install it manually, then rerun: ${UV_DOCS}`)
    process.exit(1)
  }
}

// The wizard shells out to `uv sync`, so a uv found off PATH goes on its PATH.
const env = uv === 'uv' ? process.env : { ...process.env, PATH: `${dirname(uv)}${delimiter}${process.env.PATH ?? ''}` }
// @latest skips uv's cached copy of the scaffolder.
const result = spawnSync(uv, ['tool', 'run', 'create-pywire-app@latest', ...process.argv.slice(2)], {
  stdio: 'inherit',
  env,
})

if (freshUv) {
  console.log('==> uv was just installed: restart your shell so `uv` is on your PATH.')
}
if (result.error) {
  console.error(`Error: could not run uv: ${result.error.message}`)
  process.exit(1)
}
if (result.signal) process.kill(process.pid, result.signal)
process.exit(result.status ?? 1)
