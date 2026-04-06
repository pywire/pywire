import * as path from 'path'

import { createRequire } from 'module'
import { pathToFileURL } from 'url'
import {
  workspace,
  ExtensionContext,
  window,
  commands,
  languages,
  Position,
  Range,
  TextEditor,
  TextEditorEdit,
  TextEdit,
  DocumentHighlight,
  extensions,
  Uri,
  TextDocument,
  Hover,
  Location,
  LocationLink,
  CompletionList,
  env,
  WorkspaceEdit,
  TextDocumentContentProvider,
  SignatureHelp,
  EventEmitter,
} from 'vscode'
import { LanguageClient, LanguageClientOptions, ServerOptions } from 'vscode-languageclient/node'
import { setupUpdateCheck, performUpdate } from './updateCheck'

type PrettierModule = typeof import('prettier')
type PrettierPlugin = import('prettier').Plugin

/**
 * Handles embedded JS/CSS requests by forwarding them to a virtual document.
 */
class EmbeddedLanguageSupport {
  constructor() {}

  /**
   * Check if position is inside a script or style tag.
   * Returns 'javascript' | 'css' | null
   */
  getEmbeddedMode(document: TextDocument, position: Position): 'javascript' | 'css' | null {
    const text = document.getText()
    const offset = document.offsetAt(position)

    const scriptRegex = /<script\b[^>]*>([\s\S]*?)<\/script>/g
    let match
    while ((match = scriptRegex.exec(text)) !== null) {
      if (offset >= match.index && offset <= match.index + match[0].length) {
        const openTagEnd = match.index + match[0].indexOf('>') + 1
        const closeTagStart = match.index + match[0].lastIndexOf('<')
        if (offset >= openTagEnd && offset <= closeTagStart) {
          return 'javascript'
        }
      }
    }

    const styleRegex = /<style\b[^>]*>([\s\S]*?)<\/style>/g
    while ((match = styleRegex.exec(text)) !== null) {
      if (offset >= match.index && offset <= match.index + match[0].length) {
        const openTagEnd = match.index + match[0].indexOf('>') + 1
        const closeTagStart = match.index + match[0].lastIndexOf('<')
        if (offset >= openTagEnd && offset <= closeTagStart) {
          return 'css'
        }
      }
    }
    return null
  }

  getVirtualContent(document: TextDocument, mode: 'javascript' | 'css'): string {
    const text = document.getText()
    let result = ''
    let lastIndex = 0

    const regex =
      mode === 'javascript'
        ? /<script\b[^>]*>([\s\S]*?)<\/script>/g
        : /<style\b[^>]*>([\s\S]*?)<\/style>/g

    let match
    while ((match = regex.exec(text)) !== null) {
      const preTag = text.slice(lastIndex, match.index)
      result += preTag.replace(/[^\n]/g, ' ')
      const openTagLen = match[0].indexOf('>') + 1
      const openTag = match[0].slice(0, openTagLen)
      result += openTag.replace(/[^\n]/g, ' ')
      const content = match[1]
      result += content
      const closeTagStart = match.index + openTagLen + content.length
      const closeTag = text.slice(closeTagStart, match.index + match[0].length)
      result += closeTag.replace(/[^\n]/g, ' ')
      lastIndex = match.index + match[0].length
    }
    const remainder = text.slice(lastIndex)
    result += remainder.replace(/[^\n]/g, ' ')
    return result
  }

  async forwardRequest<T>(
    document: TextDocument,
    position: Position,
    command: string,
    args: any[],
    log: (msg: string) => void
  ): Promise<T | undefined> {
    const mode = this.getEmbeddedMode(document, position)
    if (!mode) return undefined

    // Use a custom scheme to avoid "dirty" untitled files
    const vUri = Uri.parse(
      `pywire-embedded://${document.uri.path}${mode === 'css' ? '.css' : '.js'}`
    )

    try {
      // workspace.openTextDocument with a custom scheme triggers the provider.
      // But we need to make sure the provider knows WHAT content to provide.
      // Since 'document' is the source, we can just compute it.
      // BUT `provideTextDocumentContent` only takes a URI.
      // We need to find the source doc from the URI.
      // We can encode the source URI in the virtual URI query?
      // Or just look up the document in the workspace based on path (since path matches).

      // Trigger update if needed?
      // Actually, openTextDocument will call provider.
      await workspace.openTextDocument(vUri)

      // We don't use WorkspaceEdit. We rely on the provider.
      // BUT if the doc is already open, it might be stale.
      // We need to force an update.
      embeddedProviderInstance.update(vUri)

      const result = await commands.executeCommand<T>(command, vUri, ...args)
      return result
    } catch (e) {
      log(`Embedded ${command} failed for ${mode}: ${String(e)}`)
      return undefined
    }
  }
}

// Global instance to be used by the forwarded request
const embeddedSupport = new EmbeddedLanguageSupport()

class EmbeddedContentProvider implements TextDocumentContentProvider {
  private _onDidChange = new EventEmitter<Uri>()
  get onDidChange() {
    return this._onDidChange.event
  }

  update(uri: Uri) {
    this._onDidChange.fire(uri)
  }

  provideTextDocumentContent(uri: Uri): string {
    // Recover source document path...
    // uri.path is /path/to/file.wire.js
    // We want /path/to/file.wire
    // But uri.path includes the leading slash?
    const originalPath = uri.path.replace(/\.(js|css)$/, '')
    // Find doc
    const doc = workspace.textDocuments.find((d) => d.uri.path === originalPath)
    if (doc) {
      const ext = path.extname(uri.path)
      const mode = ext === '.css' ? 'css' : 'javascript'
      return embeddedSupport.getVirtualContent(doc, mode)
    }
    return ''
  }
}
const embeddedProviderInstance = new EmbeddedContentProvider()

let client: LanguageClient | null = null
let prettierModule: PrettierModule | null = null
let pywirePluginModule: unknown = null
let extensionDir: string = ''
let clientSubscriptions: { dispose(): void }[] = []
let isRestarting = false

function loadPrettierModule(): PrettierModule {
  if (prettierModule) {
    return prettierModule
  }

  // Use createRequire to load CJS modules from bundled node_modules
  const dummyModulePath = path.join(extensionDir, 'out', 'node_modules', 'index.js')
  const requireFrom = createRequire(pathToFileURL(dummyModulePath).href)
  prettierModule = requireFrom('prettier') as PrettierModule
  return prettierModule
}

function loadPywirePlugin(): unknown {
  if (pywirePluginModule) {
    return pywirePluginModule
  }

  // Use createRequire to load from bundled node_modules
  const dummyModulePath = path.join(extensionDir, 'out', 'node_modules', 'index.js')
  const requireFrom = createRequire(pathToFileURL(dummyModulePath).href)
  pywirePluginModule = requireFrom('prettier-plugin-pywire')
  return pywirePluginModule
}

/**
 * Determine which section a line is in based on the ---html--- separator.
 * Returns 'python' for lines before the separator, 'directive' for lines starting with ! or #!,
 * 'separator' for the separator line, 'html' for HTML content lines.
 */
function isFenceLine(line: string): boolean {
  return /^\s*-{3,}\s*$/.test(line)
}

function getSection(
  lines: string[],
  lineNumber: number
): 'python' | 'directive' | 'html' | 'separator' {
  const fenceIndices: number[] = []
  for (let i = 0; i < lines.length; i++) {
    if (isFenceLine(lines[i])) {
      fenceIndices.push(i)
    }
  }

  if (fenceIndices.includes(lineNumber)) {
    return 'separator'
  }

  const lineText = lines[lineNumber]?.trim() || ''

  // Fenced Python: content between first two fences
  if (fenceIndices.length >= 2) {
    if (lineNumber > fenceIndices[0] && lineNumber < fenceIndices[1]) {
      return 'python'
    }
    if (lineNumber > fenceIndices[1]) {
      return 'html'
    }
  }

  // Check for directive (must be before first fence or at top if no fences)
  const firstFence = fenceIndices.length > 0 ? fenceIndices[0] : -1
  if (
    (lineText.startsWith('!') || lineText.startsWith('# !') || lineText.startsWith('#!')) &&
    (firstFence === -1 || lineNumber < firstFence)
  ) {
    return 'directive'
  }

  // Treat everything else after last directive (or top) as HTML if no fences
  // Or if it's before the first fence and not a directive, it might be HTML (for components without python)
  if (firstFence === -1 || lineNumber < firstFence) {
    // If it's before fences and not a directive, check if there are ANY directives above
    // Actually, simple rule: if no fences, directives at top, rest is html.
    let lastDirective = -1
    for (let i = 0; i < lines.length; i++) {
      const t = lines[i].trim()
      if (t.startsWith('!') || t.startsWith('# !') || t.startsWith('#!')) {
        lastDirective = i
      } else if (t !== '' && lastDirective !== -1) {
        break
      }
    }
    return lineNumber > lastDirective ? 'html' : 'directive'
  }

  return 'html'
}

/**
 * Detect what type of comment (if any) is on a line.
 * Returns 'python' for # comments, 'html' for <!-- --> comments, or null for no comment.
 */
function detectExistingComment(line: string): 'python' | 'html' | null {
  const trimmed = line.trim()
  if (trimmed.startsWith('<!--') && trimmed.endsWith('-->')) {
    return 'html'
  }
  if (trimmed.startsWith('#')) {
    return 'python'
  }
  return null
}

/**
 * Remove comment from a line based on detected comment type.
 */
function removeComment(line: string, commentType: 'python' | 'html'): string {
  if (commentType === 'python') {
    // Remove # comment, preserving indent
    return line.replace(/^(\s*)# ?/, '$1')
  } else {
    // Remove <!-- --> comment, preserving indent
    const match = line.match(/^(\s*)<!--\s?(.*?)\s?-->(\s*)$/)
    if (match) {
      return match[1] + match[2]
    }
    return line
  }
}

/**
 * Add comment to a line based on section type.
 */
function addComment(line: string, section: 'python' | 'directive' | 'html'): string {
  const match = line.match(/^(\s*)/)
  const indent = match ? match[1] : ''
  const content = line.trimStart()

  if (section === 'python' || section === 'directive') {
    return indent + '# ' + content
  } else {
    return indent + '<!-- ' + content + ' -->'
  }
}

export function activate(context: ExtensionContext) {
  extensionDir = context.extensionPath

  const output = window.createOutputChannel('PyWire')
  const log = (message: string) => {
    output.appendLine(`[${new Date().toISOString()}] ${message}`)
  }

  console.log('PyWire extension activating...')
  log('PyWire extension activating')

  const toggleCommentCmd = commands.registerTextEditorCommand(
    'pywire.toggleComment',
    (editor: TextEditor, edit: TextEditorEdit) => {
      const document = editor.document
      if (document.languageId !== 'pywire') {
        // Fall back to default comment command for non-pywire files
        commands.executeCommand('editor.action.commentLine')
        return
      }

      const lines = document.getText().split('\n')
      const selections = editor.selections

      for (const selection of selections) {
        const startLine = selection.start.line
        const endLine = selection.end.line

        for (let lineNum = startLine; lineNum <= endLine; lineNum++) {
          const lineText = document.lineAt(lineNum).text
          const trimmed = lineText.trim()

          // Skip empty lines and separator
          if (trimmed === '' || isFenceLine(lineText)) {
            continue
          }

          // Determine section for THIS line
          const section = getSection(lines, lineNum)
          if (section === 'separator') {
            continue
          }

          // Check if line already has a comment
          const existingComment = detectExistingComment(lineText)

          let newText: string
          if (existingComment) {
            // Remove existing comment
            newText = removeComment(lineText, existingComment)
          } else {
            // Add comment based on section
            newText = addComment(lineText, section)
          }

          const lineRange = document.lineAt(lineNum).range
          edit.replace(lineRange, newText)
        }
      }
    }
  )
  context.subscriptions.push(toggleCommentCmd)

  // -- Embedded JS/CSS Support --
  // const embeddedSupport = new EmbeddedLanguageSupport() // Moved global
  context.subscriptions.push(
    workspace.registerTextDocumentContentProvider('pywire-embedded', embeddedProviderInstance)
  )

  // Registration for completion and hover
  context.subscriptions.push(
    languages.registerCompletionItemProvider(
      'pywire',
      {
        async provideCompletionItems(doc, pos, _token, context) {
          const result = await embeddedSupport.forwardRequest<CompletionList>(
            doc,
            pos,
            'vscode.executeCompletionItemProvider',
            [pos, context.triggerCharacter],
            log
          )
          if (result) {
            log(`Found completions: ${result.items.length} items`)
            return result
          }
          return undefined
        },
      },
      '.',
      '"',
      "'",
      '/',
      '<'
    )
  )

  context.subscriptions.push(
    languages.registerHoverProvider('pywire', {
      async provideHover(doc, pos, _token) {
        const result = await embeddedSupport.forwardRequest<Hover[]>(
          doc,
          pos,
          'vscode.executeHoverProvider',
          [pos],
          log
        )
        if (result && result.length > 0) return result[0]
        return undefined
      },
    })
  )

  context.subscriptions.push(
    languages.registerDefinitionProvider('pywire', {
      async provideDefinition(doc, pos, _token) {
        const result = await embeddedSupport.forwardRequest<Location | Location[] | LocationLink[]>(
          doc,
          pos,
          'vscode.executeDefinitionProvider',
          [pos],
          log
        )
        if (!result) return undefined

        const remapUri = (u: Uri) => {
          if (
            u.scheme === 'pywire-embedded' &&
            (u.path.endsWith('.js') || u.path.endsWith('.css'))
          ) {
            if (u.path.startsWith(doc.uri.path)) {
              return doc.uri
            }
          }
          return u
        }

        if (Array.isArray(result)) {
          // Check if it's Location[] or LocationLink[]
          if (result.length > 0) {
            const first = result[0]
            if ('targetUri' in first) {
              // LocationLink[]
              return (result as LocationLink[]).map((l) => ({
                ...l,
                targetUri: remapUri(l.targetUri),
              }))
            } else {
              // Location[]
              return (result as Location[]).map((l) => new Location(remapUri(l.uri), l.range))
            }
          }
          return []
        } else {
          // Single Location
          return new Location(remapUri((result as Location).uri), (result as Location).range)
        }
      },
    })
  )

  context.subscriptions.push(
    languages.registerReferenceProvider('pywire', {
      async provideReferences(doc, pos, context, _token) {
        const result = await embeddedSupport.forwardRequest<Location[]>(
          doc,
          pos,
          'vscode.executeReferenceProvider',
          [pos, context],
          log
        )
        if (result) {
          return result.map((l) => {
            if (l.uri.scheme === 'pywire-embedded' && l.uri.path.startsWith(doc.uri.path)) {
              return new Location(doc.uri, l.range)
            }
            return l
          })
        }
        return result
      },
    })
  )

  context.subscriptions.push(
    languages.registerRenameProvider('pywire', {
      async provideRenameEdits(doc, pos, newName, _token) {
        const result = await embeddedSupport.forwardRequest<WorkspaceEdit>(
          doc,
          pos,
          'vscode.executeDocumentRenameProvider',
          [pos, newName],
          log
        )
        if (result) {
          const newEdit = new WorkspaceEdit()
          for (const [uri, edits] of result.entries()) {
            // Remap edits from virtual URI to original document URI.
            // We assume edits are local to the file.
            // If the rename affects other files (e.g. imports), we'd need to check if those are also virtual files
            // and map them back to their corresponding .wire files.
            // For now, simpler logic: check if it matches OUR virtual uri.
            const vUriPath = doc.uri.path + (uri.path.endsWith('.css') ? '.css' : '.js')
            if (
              uri.path === vUriPath &&
              (uri.scheme === 'untitled' || uri.scheme === 'pywire-embedded')
            ) {
              newEdit.set(doc.uri, edits)
            } else {
              // It's some other file? Keep it as is?
              newEdit.set(uri, edits)
            }
          }
          return newEdit
        }
        return result
      },
    })
  )

  context.subscriptions.push(
    languages.registerSignatureHelpProvider(
      'pywire',
      {
        async provideSignatureHelp(doc, pos, _token, context) {
          const result = await embeddedSupport.forwardRequest<SignatureHelp>(
            doc,
            pos,
            'vscode.executeSignatureHelpProvider',
            [pos, context.triggerCharacter],
            log
          )
          return result
        },
      },
      '(',
      ','
    )
  )

  context.subscriptions.push(
    languages.registerDocumentHighlightProvider('pywire', {
      async provideDocumentHighlights(doc, pos, _token) {
        const result = await embeddedSupport.forwardRequest<DocumentHighlight[]>(
          doc,
          pos,
          'vscode.executeDocumentHighlights',
          [pos],
          log
        )
        return result
      },
    })
  )

  const formattingProvider = languages.registerDocumentFormattingEditProvider(
    { language: 'pywire' },
    {
      async provideDocumentFormattingEdits(document: TextDocument) {
        const text = document.getText()
        if (text.trim().length === 0) {
          return []
        }

        try {
          const prettier = loadPrettierModule()
          const prettierAny = prettier as PrettierModule & { default?: PrettierModule }
          const formatFn = prettierAny.format ?? prettierAny.default?.format
          if (typeof formatFn !== 'function') {
            throw new Error('Prettier format function not available')
          }

          const pluginModule = loadPywirePlugin()
          const pywirePlugin =
            (pluginModule as { default?: PrettierPlugin }).default ??
            (pluginModule as PrettierPlugin)
          const formatted = await formatFn(text, {
            parser: 'pywire',
            plugins: [pywirePlugin],
            filepath: document.fileName,
          })
          if (formatted === text) {
            return []
          }

          const fullRange = new Range(document.positionAt(0), document.positionAt(text.length))
          return [TextEdit.replace(fullRange, formatted)]
        } catch (e) {
          console.error('PyWire format failed', e)
          log(`PyWire format failed: ${String(e)}`)
          return []
        }
      },
    }
  )
  context.subscriptions.push(formattingProvider)

  // Path to LSP server script (launcher)
  const serverScript = context.asAbsolutePath(path.join('out', 'lsp_launcher.py'))

  console.log('LSP server script:', serverScript)
  log(`LSP server script: ${serverScript}`)

  // Function to stop the language client and clean up subscriptions
  async function stopLanguageClient() {
    // Dispose all client-related subscriptions
    for (const sub of clientSubscriptions) {
      try {
        sub.dispose()
      } catch {
        // Ignore disposal errors
      }
    }
    clientSubscriptions = []

    // Stop the client
    if (client) {
      try {
        await client.stop()
      } catch (e) {
        console.error('Error stopping client', e)
      }
      client = null
    }
  }

  // Function to start the language client
  async function startLanguageClient() {
    // Get Python path from settings
    const config = workspace.getConfiguration('pywire')
    let pythonPath = config.get<string>('pythonPath')
    try {
      // If no explicit path set, try to get it from the Python extension
      if (!pythonPath) {
        const pythonExtension = extensions.getExtension('ms-python.python')
        if (pythonExtension) {
          if (!pythonExtension.isActive) {
            await pythonExtension.activate()
          }
          const exports = pythonExtension.exports
          // Use the public API to get the execution details
          if (exports.settings && exports.settings.getExecutionDetails) {
            const executionDetails = exports.settings.getExecutionDetails(
              workspace.workspaceFolders?.[0]?.uri
            )
            pythonPath = executionDetails?.execCommand?.[0]
          }
        }
      }

      if (!pythonPath) {
        // Last resort fallback
        pythonPath = 'python3'
      }
      console.log(`Using Python interpreter: ${pythonPath}`)
      log(`Using Python interpreter: ${pythonPath}`)

      // Server options - how to start the server
      const serverOptions: ServerOptions = {
        command: pythonPath,
        args: [serverScript],
        options: {
          env: { ...process.env },
        },
      }

      // Client options - what to send to the server
      const clientOptions: LanguageClientOptions = {
        documentSelector: [{ scheme: 'file', language: 'pywire' }],
        synchronize: {
          fileEvents: workspace.createFileSystemWatcher('**/*.pywire'),
        },
        initializationOptions: {
          tyPath: config.get<string>('tyPath'),
        },
      }

      // Create the language client
      client = new LanguageClient(
        'pywireLanguageServer',
        'PyWire Language Server',
        serverOptions,
        clientOptions
      )

      await client.start()
      console.log('PyWire language server started')
      log('PyWire language server started')

      window.showInformationMessage('PyWire services are running')
    } catch (err) {
      console.error('Failed to start PyWire services:', err)
      window.showErrorMessage('Failed to start PyWire services: ' + err)
      log(`Failed to start PyWire services: ${String(err)}`)
    }
  }

  // Function to restart the language client
  async function restartLanguageClient() {
    if (isRestarting) {
      return
    }
    isRestarting = true
    log('Restarting language server...')
    try {
      await stopLanguageClient()
      await startLanguageClient()
      log('Language server restarted successfully')
    } catch (e) {
      log(`Failed to restart language server: ${String(e)}`)
      window.showErrorMessage('Failed to restart PyWire Language Server: ' + e)
    } finally {
      isRestarting = false
    }
  }

  // Register restart command
  const restartCmd = commands.registerCommand('pywire.restartLanguageServer', async () => {
    await restartLanguageClient()
  })
  context.subscriptions.push(restartCmd)

  // Register Update command
  context.subscriptions.push(
    commands.registerCommand('pywire.update', async () => {
      await performUpdate()
    })
  )

  // Register Open Docs commands
  context.subscriptions.push(
    commands.registerCommand('pywire.openDocs', () => {
      env.openExternal(Uri.parse('https://pywire.dev/docs'))
    })
  )

  context.subscriptions.push(
    commands.registerCommand('pywire.openDocsNightly', () => {
      env.openExternal(Uri.parse('https://nightly.pywire.dev/docs'))
    })
  )

  // Register Run Dev command
  context.subscriptions.push(
    commands.registerCommand('pywire.runDev', () => {
      const terminalName = 'PyWire Dev'
      let terminal = window.terminals.find((t) => t.name === terminalName)
      if (terminal) {
        terminal.show()
        terminal.sendText('\u0003') // Send Ctrl+C
      } else {
        terminal = window.createTerminal(terminalName)
        terminal.show()
      }
      terminal.sendText('uv run pywire dev --no-tui')
      commands.executeCommand('setContext', 'pywire.devServerRunning', true)
    })
  )

  context.subscriptions.push(
    commands.registerCommand('pywire.stopDev', () => {
      const terminalName = 'PyWire Dev'
      const terminal = window.terminals.find((t) => t.name === terminalName)
      if (terminal) {
        terminal.sendText('\u0003') // Send Ctrl+C
      }
      commands.executeCommand('setContext', 'pywire.devServerRunning', false)
    })
  )

  // Listen for terminal closure to reset context
  // Listen for terminal closure to reset context
  context.subscriptions.push(
    window.onDidCloseTerminal((terminal) => {
      if (terminal.name === 'PyWire Dev') {
        commands.executeCommand('setContext', 'pywire.devServerRunning', false)
      }
    })
  )

  // Start the client initially
  startLanguageClient()

  // Setup periodic update checks
  setupUpdateCheck(context)
}

export function deactivate(): Promise<void> | undefined {
  if (!client) {
    return undefined
  }
  return client.stop()
}
