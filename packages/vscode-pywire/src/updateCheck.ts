import * as vscode from 'vscode'
import * as path from 'path'
import { exec } from 'child_process'
import { promisify } from 'util'
import { fetchLatestLSVersionFromPyPI, getInstalledLSVersion, upgradeLS } from './lsServerManager'

const execAsync = promisify(exec)

interface OutdatedPackage {
  name: string
  version: string
  latest_version: string
}

interface UpdateHooks {
  output: vscode.OutputChannel
  restartClient: () => Promise<void>
}

let hooks: UpdateHooks | null = null

export function setupUpdateCheck(context: vscode.ExtensionContext, updateHooks: UpdateHooks) {
  hooks = updateHooks
  setTimeout(() => checkForUpdates(context), 5000)
  const interval = setInterval(() => checkForUpdates(context), 5 * 60 * 1000)
  context.subscriptions.push({ dispose: () => clearInterval(interval) })
}

async function checkForUpdates(context: vscode.ExtensionContext) {
  const config = vscode.workspace.getConfiguration('pywire')
  if (config.get('disableUpdateNotifications')) {
    return
  }

  await checkLSUpdate(context)
  await checkPywireProjectUpdate()
}

async function checkLSUpdate(context: vscode.ExtensionContext) {
  const config = vscode.workspace.getConfiguration('pywire')
  const versionPref = config.get<string>('languageServer.version') || 'latest'
  if (versionPref !== 'latest') return
  if (config.get<string>('languageServer.customPath')) return

  const venvPython = lsVenvPython(context)
  const installed = await getInstalledLSVersion(venvPython)
  if (!installed) return
  const latest = await fetchLatestLSVersionFromPyPI()
  if (!latest || latest === installed) return

  const selection = await vscode.window.showInformationMessage(
    `PyWire Language Server update available: ${installed} -> ${latest}.`,
    'Upgrade',
    'Dismiss',
    'Silence'
  )
  if (selection === 'Upgrade') {
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: `Updating PyWire Language Server to ${latest}...`,
        cancellable: false,
      },
      async () => {
        try {
          await upgradeLS(context, latest, hooks!.output)
          await hooks!.restartClient()
          vscode.window.showInformationMessage(`PyWire Language Server updated to ${latest}.`)
        } catch (e) {
          vscode.window.showErrorMessage(`Failed to upgrade PyWire Language Server: ${String(e)}`)
        }
      }
    )
  } else if (selection === 'Silence') {
    await config.update('disableUpdateNotifications', true, vscode.ConfigurationTarget.Global)
    vscode.window.showInformationMessage('Update notifications have been disabled in settings.')
  }
}

function lsVenvPython(context: vscode.ExtensionContext): string {
  const venvPath = path.join(context.globalStorageUri.fsPath, 'ls-venv')
  return process.platform === 'win32'
    ? path.join(venvPath, 'Scripts', 'python.exe')
    : path.join(venvPath, 'bin', 'python')
}

async function checkPywireProjectUpdate() {
  const workspaceFolders = vscode.workspace.workspaceFolders
  if (!workspaceFolders || workspaceFolders.length === 0) {
    return
  }

  const rootPath = workspaceFolders[0].uri.fsPath

  try {
    const { stdout } = await execAsync('uv pip list --outdated --format json', { cwd: rootPath })
    if (!stdout.trim()) {
      return
    }

    const outdated: OutdatedPackage[] = JSON.parse(stdout)
    const pywireUpdate = outdated.find((pkg) => pkg.name === 'pywire')

    if (pywireUpdate) {
      showPywireUpdateNotification(rootPath, pywireUpdate.latest_version, pywireUpdate.version)
    }
  } catch (e) {
    console.error('Failed to check for updates with uv:', e)
  }
}

async function showPywireUpdateNotification(
  cwd: string,
  newVersion: string,
  currentVersion: string
) {
  const selection = await vscode.window.showInformationMessage(
    `A new version of PyWire is available: ${currentVersion} -> ${newVersion}.`,
    'Upgrade',
    'Dismiss',
    'Silence'
  )

  if (selection === 'Upgrade') {
    performUpdate(cwd)
  } else if (selection === 'Silence') {
    await vscode.workspace
      .getConfiguration('pywire')
      .update('disableUpdateNotifications', true, vscode.ConfigurationTarget.Global)
    vscode.window.showInformationMessage('Update notifications have been disabled in settings.')
  }
}

export async function performUpdate(cwd?: string) {
  if (!cwd) {
    const workspaceFolders = vscode.workspace.workspaceFolders
    if (!workspaceFolders || workspaceFolders.length === 0) {
      vscode.window.showErrorMessage('No workspace open to perform PyWire update.')
      return
    }
    cwd = workspaceFolders[0].uri.fsPath
  }

  vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: 'Updating PyWire...',
      cancellable: false,
    },
    async (_progress) => {
      try {
        await execAsync('uv sync --upgrade-package pywire', { cwd })
        vscode.window.showInformationMessage('PyWire updated successfully.')
      } catch (error: unknown) {
        const stderr =
          (error as { stderr?: string; message?: string }).stderr || (error as Error).message || ''
        if (
          stderr.includes('resolution failed') ||
          stderr.includes('conflict') ||
          stderr.includes('constraint')
        ) {
          vscode.window.showWarningMessage(
            'PyWire update failed due to version constraints. Please check your pyproject.toml.'
          )
        } else {
          vscode.window.showErrorMessage(`PyWire update failed: ${stderr.substring(0, 200)}...`)
        }
        console.error('Update failed', error)
      }
    }
  )
}
