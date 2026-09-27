// Tests for the npm entry point (`npx create-pywire-app`, `npm create pywire-app`).
// Each test runs the real bin script with a sandboxed HOME and a PATH of fake
// `uv`/`curl` binaries that log how they were called.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const PKG_DIR = new URL('..', import.meta.url).pathname
const pkg = JSON.parse(readFileSync(join(PKG_DIR, 'package.json'), 'utf8'))
const BIN = join(PKG_DIR, pkg.bin?.['create-pywire-app'] ?? 'missing-bin')
const SYSTEM_PATH = '/usr/bin:/bin'

function exe(path, body) {
  writeFileSync(path, `#!/bin/sh\n${body}\n`)
  chmodSync(path, 0o755)
}

// A fake uv: logs its argv, whether stdin is a TTY, and the first stdin line.
function fakeUv(dir, log) {
  mkdirSync(dir, { recursive: true })
  exe(
    join(dir, 'uv'),
    `[ "$1" = "--version" ] && { echo "uv 0.0.0"; exit 0; }
printf '%s\\n' "uv $*" >> ${log}
command -v uv >/dev/null && echo uv-on-path >> ${log}
if [ -t 0 ]; then echo stdin=tty >> ${log}; else read -r line; echo "stdin=$line" >> ${log}; fi
exit \${FAKE_UV_EXIT:-0}`,
  )
}

function sandbox() {
  const root = mkdtempSync(join(tmpdir(), 'create-pywire-app-npm-'))
  const box = { root, home: join(root, 'home'), bin: join(root, 'bin'), log: join(root, 'calls.log') }
  mkdirSync(box.home)
  mkdirSync(box.bin)
  return box
}

function calls(box) {
  return existsSync(box.log) ? readFileSync(box.log, 'utf8').trim().split('\n') : []
}

function run(box, args = [], { env = {}, input = 'typed-answer\n' } = {}) {
  return spawnSync(process.execPath, [BIN, ...args], {
    input,
    env: { HOME: box.home, PATH: `${box.bin}:${SYSTEM_PATH}`, ...env },
    encoding: 'utf8',
  })
}

test('is published as create-pywire-app with a runnable bin', () => {
  assert.equal(pkg.name, 'create-pywire-app')
  assert.ok(existsSync(BIN), `bin ${BIN} must exist`)
  assert.match(readFileSync(BIN, 'utf8'), /^#!\/usr\/bin\/env node\n/)
  assert.ok(pkg.files.includes('bin'), 'bin/ must be in the published files')
  assert.deepEqual(pkg.dependencies ?? {}, {}, 'the shim has no runtime dependencies')
})

test('runs the latest create-pywire-app through uv and passes args through', () => {
  const box = sandbox()
  fakeUv(box.bin, box.log)
  const r = run(box, ['my-app', '--yes', '--template', 'blog'])
  assert.equal(r.status, 0, r.stderr)
  assert.ok(calls(box).includes('uv tool run create-pywire-app@latest my-app --yes --template blog'), calls(box).join('\n'))
})

test('hands its stdin to the wizard so prompts can be answered', () => {
  const box = sandbox()
  fakeUv(box.bin, box.log)
  const r = run(box)
  assert.equal(r.status, 0, r.stderr)
  assert.ok(calls(box).includes('stdin=typed-answer'), calls(box).join('\n'))
})

test('keeps the terminal attached for the interactive wizard', { skip: process.platform !== 'linux' }, () => {
  const box = sandbox()
  fakeUv(box.bin, box.log)
  const r = spawnSync('script', ['-qec', `${process.execPath} ${BIN}`, '/dev/null'], {
    env: { HOME: box.home, PATH: `${box.bin}:${SYSTEM_PATH}` },
    encoding: 'utf8',
  })
  assert.equal(r.status, 0, r.stderr)
  assert.ok(calls(box).includes('stdin=tty'), calls(box).join('\n'))
})

test('propagates the create-pywire-app exit code', () => {
  const box = sandbox()
  fakeUv(box.bin, box.log)
  const r = run(box, [], { env: { FAKE_UV_EXIT: '3' } })
  assert.equal(r.status, 3)
})

test('finds uv in ~/.local/bin when a fresh install is not on PATH yet', () => {
  const box = sandbox()
  fakeUv(join(box.home, '.local', 'bin'), box.log)
  exe(join(box.bin, 'curl'), `echo "curl $*" >> ${box.log}; exit 1`)
  const r = run(box, ['my-app'])
  assert.equal(r.status, 0, r.stderr)
  const log = calls(box)
  assert.ok(!log.some((l) => l.startsWith('curl')), 'must not reinstall uv')
  assert.ok(log.includes('uv tool run create-pywire-app@latest my-app'), log.join('\n'))
})

test('installs uv when it is missing, then runs create-pywire-app', () => {
  const box = sandbox()
  const dist = join(box.root, 'uv-dist')
  fakeUv(dist, box.log)
  // The fake astral installer (fetched by curl) drops uv into ~/.local/bin.
  exe(
    join(box.bin, 'curl'),
    `echo "curl $*" >> ${box.log}
cat <<'EOF'
mkdir -p "$HOME/.local/bin" && cp ${dist}/uv "$HOME/.local/bin/uv"
EOF`,
  )
  const r = run(box, ['my-app'])
  assert.equal(r.status, 0, r.stderr)
  const log = calls(box)
  assert.ok(log.includes('curl -LsSf https://astral.sh/uv/install.sh'), log.join('\n'))
  assert.ok(log.includes('uv tool run create-pywire-app@latest my-app'), log.join('\n'))
  // The wizard shells out to `uv sync`, so the fresh uv must be on its PATH.
  assert.ok(log.includes('uv-on-path'), log.join('\n'))
  assert.match(r.stdout + r.stderr, /restart your shell/i)
})

test('fails with a pointer to the uv docs when uv cannot be installed', () => {
  const box = sandbox()
  exe(join(box.bin, 'curl'), 'exit 22')
  const r = run(box)
  assert.equal(r.status, 1)
  assert.match(r.stderr, /docs\.astral\.sh\/uv/)
})
