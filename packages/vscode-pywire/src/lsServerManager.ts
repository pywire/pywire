import * as fs from 'fs'
import * as path from 'path'
import * as https from 'https'
import * as os from 'os'
import { spawn } from 'child_process'
import {
  workspace,
  extensions,
  ExtensionContext,
  OutputChannel,
  window,
  ProgressLocation,
} from 'vscode'

const LS_PACKAGE = 'pywire-language-server'
const DEFAULT_PYTHON_VERSION = '3.12'
const PYPI_URL = `https://pypi.org/pypi/${LS_PACKAGE}/json`
const UV_LATEST_BASE = 'https://github.com/astral-sh/uv/releases/latest/download'

export interface LSResolved {
  venvPython: string
  installedVersion: string
}

interface ExecResult {
  code: number
  stdout: string
  stderr: string
}

function execCapture(
  cmd: string,
  args: string[],
  log?: OutputChannel,
  env?: Record<string, string | undefined>
): Promise<ExecResult> {
  return new Promise((resolve) => {
    log?.appendLine(`$ ${cmd} ${args.join(' ')}`)
    const child = spawn(cmd, args, { env: env ?? process.env })
    let stdout = ''
    let stderr = ''
    child.stdout.on('data', (d) => {
      const s = d.toString()
      stdout += s
    })
    child.stderr.on('data', (d) => {
      const s = d.toString()
      stderr += s
      log?.append(s)
    })
    child.on('close', (code) => {
      resolve({ code: code ?? -1, stdout, stderr })
    })
    child.on('error', (e) => {
      resolve({ code: -1, stdout, stderr: stderr + String(e) })
    })
  })
}

async function commandExists(cmd: string): Promise<boolean> {
  const which = process.platform === 'win32' ? 'where' : 'which'
  const res = await execCapture(which, [cmd])
  return res.code === 0
}

function httpsGet(url: string, maxRedirects = 5): Promise<{ statusCode: number; body: Buffer }> {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { headers: { 'user-agent': 'vscode-pywire' } }, (res) => {
      const status = res.statusCode ?? 0
      if (status >= 300 && status < 400 && res.headers.location && maxRedirects > 0) {
        res.resume()
        const next = new URL(res.headers.location, url).toString()
        httpsGet(next, maxRedirects - 1).then(resolve, reject)
        return
      }
      const chunks: Buffer[] = []
      res.on('data', (c) => chunks.push(c))
      res.on('end', () => resolve({ statusCode: status, body: Buffer.concat(chunks) }))
      res.on('error', reject)
    })
    req.on('error', reject)
  })
}

async function httpsDownload(url: string, destPath: string): Promise<void> {
  const { statusCode, body } = await httpsGet(url)
  if (statusCode !== 200) {
    throw new Error(`Download failed (${statusCode}): ${url}`)
  }
  fs.writeFileSync(destPath, body)
}

function uvAssetName(): { name: string; archive: 'tar.gz' | 'zip' } {
  const platform = process.platform
  const arch = process.arch
  if (platform === 'darwin') {
    const triple = arch === 'arm64' ? 'aarch64-apple-darwin' : 'x86_64-apple-darwin'
    return { name: `uv-${triple}.tar.gz`, archive: 'tar.gz' }
  }
  if (platform === 'linux') {
    const triple = arch === 'arm64' ? 'aarch64-unknown-linux-gnu' : 'x86_64-unknown-linux-gnu'
    return { name: `uv-${triple}.tar.gz`, archive: 'tar.gz' }
  }
  if (platform === 'win32') {
    const triple = arch === 'arm64' ? 'aarch64-pc-windows-msvc' : 'x86_64-pc-windows-msvc'
    return { name: `uv-${triple}.zip`, archive: 'zip' }
  }
  throw new Error(`Unsupported platform: ${platform}/${arch}`)
}

async function extractArchive(
  archivePath: string,
  destDir: string,
  kind: 'tar.gz' | 'zip',
  log: OutputChannel
): Promise<void> {
  fs.mkdirSync(destDir, { recursive: true })
  if (kind === 'tar.gz') {
    const res = await execCapture('tar', ['-xzf', archivePath, '-C', destDir], log)
    if (res.code !== 0) throw new Error(`tar failed: ${res.stderr}`)
  } else {
    // Windows zip
    const res = await execCapture(
      'powershell',
      [
        '-NoProfile',
        '-Command',
        `Expand-Archive -LiteralPath '${archivePath}' -DestinationPath '${destDir}' -Force`,
      ],
      log
    )
    if (res.code !== 0) throw new Error(`Expand-Archive failed: ${res.stderr}`)
  }
}

function findUvBinary(root: string): string | null {
  // Archives extract to a subdirectory like uv-<triple>/uv
  const uvName = process.platform === 'win32' ? 'uv.exe' : 'uv'
  const direct = path.join(root, uvName)
  if (fs.existsSync(direct)) return direct
  for (const entry of fs.readdirSync(root)) {
    const p = path.join(root, entry, uvName)
    if (fs.existsSync(p)) return p
  }
  return null
}

async function ensureUv(globalStorageDir: string, log: OutputChannel): Promise<string> {
  if (await commandExists('uv')) {
    log.appendLine('Found uv on PATH')
    return 'uv'
  }
  const binDir = path.join(globalStorageDir, 'bin')
  const uvName = process.platform === 'win32' ? 'uv.exe' : 'uv'
  const cached = path.join(binDir, uvName)
  if (fs.existsSync(cached)) {
    log.appendLine(`Using cached uv: ${cached}`)
    return cached
  }
  log.appendLine('Downloading uv from GitHub releases...')
  const asset = uvAssetName()
  const tmpArchive = path.join(os.tmpdir(), asset.name)
  await httpsDownload(`${UV_LATEST_BASE}/${asset.name}`, tmpArchive)
  const extractDir = path.join(globalStorageDir, 'uv-extract')
  fs.rmSync(extractDir, { recursive: true, force: true })
  await extractArchive(tmpArchive, extractDir, asset.archive, log)
  const found = findUvBinary(extractDir)
  if (!found) throw new Error('uv binary not found in downloaded archive')
  fs.mkdirSync(binDir, { recursive: true })
  fs.copyFileSync(found, cached)
  if (process.platform !== 'win32') fs.chmodSync(cached, 0o755)
  fs.rmSync(extractDir, { recursive: true, force: true })
  fs.rmSync(tmpArchive, { force: true })
  log.appendLine(`Installed uv: ${cached}`)
  return cached
}

async function resolveUserPython(log: OutputChannel): Promise<string | null> {
  const config = workspace.getConfiguration('pywire')
  const configured = config.get<string>('pythonPath')
  if (configured && configured !== 'python3') {
    return configured
  }
  try {
    const pythonExt = extensions.getExtension('ms-python.python')
    if (pythonExt) {
      if (!pythonExt.isActive) await pythonExt.activate()
      const exportsApi = pythonExt.exports
      if (exportsApi?.settings?.getExecutionDetails) {
        const details = exportsApi.settings.getExecutionDetails(
          workspace.workspaceFolders?.[0]?.uri
        )
        const p = details?.execCommand?.[0]
        if (p) return p
      }
    }
  } catch (e) {
    log.appendLine(`ms-python.python discovery failed: ${String(e)}`)
  }
  if (configured) return configured
  if (await commandExists('python3')) return 'python3'
  if (await commandExists('python')) return 'python'
  return null
}

function venvPythonPath(venvPath: string): string {
  return process.platform === 'win32'
    ? path.join(venvPath, 'Scripts', 'python.exe')
    : path.join(venvPath, 'bin', 'python')
}

async function createVenv(
  uv: string,
  userPython: string | null,
  venvPath: string,
  log: OutputChannel
): Promise<void> {
  fs.mkdirSync(path.dirname(venvPath), { recursive: true })
  const args = ['venv', venvPath]
  if (userPython) {
    args.push('--python', userPython)
  } else {
    args.push('--python', DEFAULT_PYTHON_VERSION)
  }
  const res = await execCapture(uv, args, log)
  if (res.code !== 0) {
    throw new Error(`uv venv failed: ${res.stderr || res.stdout}`)
  }
}

async function installLS(
  uv: string,
  venvPython: string,
  spec: string,
  log: OutputChannel
): Promise<void> {
  const args = ['pip', 'install', '--python', venvPython, spec]
  const res = await execCapture(uv, args, log)
  if (res.code !== 0) {
    throw new Error(`uv pip install ${spec} failed: ${res.stderr || res.stdout}`)
  }
}

export async function getInstalledLSVersion(venvPython: string): Promise<string | null> {
  if (!fs.existsSync(venvPython)) return null
  const res = await execCapture(venvPython, ['-m', 'pip', 'show', LS_PACKAGE])
  if (res.code !== 0) return null
  const match = res.stdout.match(/^Version:\s*(\S+)/m)
  return match ? match[1] : null
}

export async function fetchLatestLSVersionFromPyPI(): Promise<string | null> {
  try {
    const { statusCode, body } = await httpsGet(PYPI_URL)
    if (statusCode !== 200) return null
    const parsed = JSON.parse(body.toString('utf8')) as { info?: { version?: string } }
    return parsed.info?.version ?? null
  } catch {
    return null
  }
}

function resolveTargetSpec(config: { version: string }, latest: string | null): string {
  if (config.version === 'latest') {
    return latest ? `${LS_PACKAGE}==${latest}` : LS_PACKAGE
  }
  return `${LS_PACKAGE}==${config.version}`
}

function versionFromSpec(spec: string): string | null {
  const m = spec.match(/==\s*(\S+)/)
  return m ? m[1] : null
}

export async function ensureLSInstalled(
  context: ExtensionContext,
  log: OutputChannel
): Promise<LSResolved> {
  const config = workspace.getConfiguration('pywire')
  const customPath = config.get<string>('languageServer.customPath')
  if (customPath) {
    const version = (await getInstalledLSVersion(customPath)) ?? 'unknown'
    log.appendLine(`Using customPath: ${customPath} (version ${version})`)
    return { venvPython: customPath, installedVersion: version }
  }

  const versionPref = config.get<string>('languageServer.version') || 'latest'
  const globalStorageDir = context.globalStorageUri.fsPath
  fs.mkdirSync(globalStorageDir, { recursive: true })
  const venvPath = path.join(globalStorageDir, 'ls-venv')
  const venvPython = venvPythonPath(venvPath)

  const installed = await getInstalledLSVersion(venvPython)
  const latest = versionPref === 'latest' ? await fetchLatestLSVersionFromPyPI() : null
  const targetSpec = resolveTargetSpec({ version: versionPref }, latest)
  const targetVersion = versionFromSpec(targetSpec)

  if (installed && (!targetVersion || installed === targetVersion)) {
    return { venvPython, installedVersion: installed }
  }

  await window.withProgress(
    {
      location: ProgressLocation.Notification,
      title: installed
        ? `Updating PyWire Language Server to ${targetVersion}...`
        : 'Installing PyWire Language Server...',
      cancellable: false,
    },
    async () => {
      const uv = await ensureUv(globalStorageDir, log)
      if (!fs.existsSync(venvPython)) {
        const userPython = await resolveUserPython(log)
        log.appendLine(`Resolved Python: ${userPython ?? '(uv-managed)'}`)
        await createVenv(uv, userPython, venvPath, log)
      }
      await installLS(uv, venvPython, targetSpec, log)
    }
  )

  const finalVersion = (await getInstalledLSVersion(venvPython)) ?? targetVersion ?? 'unknown'
  log.appendLine(`PyWire Language Server ready: ${finalVersion} at ${venvPython}`)
  return { venvPython, installedVersion: finalVersion }
}

export async function upgradeLS(
  context: ExtensionContext,
  targetVersion: string,
  log: OutputChannel
): Promise<string> {
  const config = workspace.getConfiguration('pywire')
  const customPath = config.get<string>('languageServer.customPath')
  if (customPath) {
    throw new Error('Cannot upgrade: pywire.languageServer.customPath is set')
  }
  const globalStorageDir = context.globalStorageUri.fsPath
  const venvPath = path.join(globalStorageDir, 'ls-venv')
  const venvPython = venvPythonPath(venvPath)
  if (!fs.existsSync(venvPython)) {
    throw new Error('Language server venv not found; run install first')
  }
  const uv = await ensureUv(globalStorageDir, log)
  await installLS(uv, venvPython, `${LS_PACKAGE}==${targetVersion}`, log)
  return venvPython
}
