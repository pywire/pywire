import * as vscode from 'vscode'
import { exec } from 'child_process'
import { promisify } from 'util'

const execAsync = promisify(exec)

interface OutdatedPackage {
  name: string
  version: string
  latest_version: string
}

export function setupUpdateCheck(context: vscode.ExtensionContext) {
  // Run immediately (with a slight delay to let startup finish)
  setTimeout(() => checkForUpdates(), 5000)

  // Run every 10 minutes
  const interval = setInterval(() => checkForUpdates(), 10 * 60 * 1000)
  context.subscriptions.push({ dispose: () => clearInterval(interval) })
}

async function checkForUpdates() {
  const config = vscode.workspace.getConfiguration('pywire')
  if (config.get('disableUpdateNotifications')) {
    return
  }

  const workspaceFolders = vscode.workspace.workspaceFolders
  if (!workspaceFolders || workspaceFolders.length === 0) {
    return
  }

  const rootPath = workspaceFolders[0].uri.fsPath

  try {
    // Use uv pip list --outdated --format json to check for updates
    // This is stable and handles registry auth/config via uv
    const { stdout } = await execAsync('uv pip list --outdated --format json', { cwd: rootPath })
    if (!stdout.trim()) {
      return
    }

    const outdated: OutdatedPackage[] = JSON.parse(stdout)
    const pywireUpdate = outdated.find((pkg) => pkg.name === 'pywire')

    if (pywireUpdate) {
      showUpdateNotification(rootPath, pywireUpdate.latest_version, pywireUpdate.version)
    }
  } catch (e) {
    // Silently fail or log to output channel?
    // We don't want to nag the user if uv is not installed or network is down.
    console.error('Failed to check for updates with uv:', e)
  }
}

async function showUpdateNotification(cwd: string, newVersion: string, currentVersion: string) {
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
        // Use uv sync --upgrade-package pywire instead of uv add
        await execAsync('uv sync --upgrade-package pywire', { cwd })
        vscode.window.showInformationMessage('PyWire updated successfully.')
      } catch (error: unknown) {
        const stderr =
          (error as { stderr?: string; message?: string }).stderr || (error as Error).message || ''
        // Check for common constraint issues in stderr
        // This is heuristic, but helpful
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
