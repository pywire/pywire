import * as path from 'path'
import * as fs from 'fs'
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
  extensions,
  Uri,
  TextDocument,
  CancellationToken,
  Hover,
  Location,
  LocationLink,
  CompletionItem,
  CompletionList,
  ReferenceContext,
  CompletionContext,
} from 'vscode'
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
  ProvideHoverSignature,
  ProvideDefinitionSignature,
  ProvideReferencesSignature,
  ProvideCompletionItemsSignature,
} from 'vscode-languageclient/node'

type PrettierModule = typeof import('prettier')
type PrettierPlugin = import('prettier').Plugin

let client: LanguageClient
let prettierModule: PrettierModule | null = null
let pywirePluginModule: unknown = null
let extensionDir: string = ''

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

interface PositionMapping {
  line: number
  character: number
}

interface VirtualCodeResponse {
  content?: string
}

/**
 * Determine which section a line is in based on the ---html--- separator.
 * Returns 'python' for lines before the separator, 'directive' for lines starting with ! or #!,
 * 'separator' for the separator line, 'html' for HTML content lines.
 */
function isSeparatorLine(line: string): boolean {
  return /^\\s*(-{3,})\\s*html\\s*\\1\\s*$/i.test(line)
}

function getSection(
  lines: string[],
  lineNumber: number
): 'python' | 'directive' | 'html' | 'separator' {
  let separatorLine = -1
  for (let i = 0; i < lines.length; i++) {
    if (isSeparatorLine(lines[i])) {
      separatorLine = i
      break
    }
  }

  if (lineNumber === separatorLine) {
    return 'separator'
  }

  const lineText = lines[lineNumber]?.trim() || ''
  // Check for directive or commented directive (must be before separator)
  if (
    (lineText.startsWith('!') || lineText.startsWith('# !') || lineText.startsWith('#!')) &&
    (separatorLine === -1 || lineNumber < separatorLine)
  ) {
    return 'directive'
  }

  if (separatorLine !== -1) {
    if (lineNumber < separatorLine) {
      return 'python'
    } else {
      return 'html'
    }
  }

  // No separator found - treat everything as python except directives at top
  return 'python'
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

/**
 * Map a location from a shadow .py file back to the original .wire file.
 */
async function mapLocationBack(
  location: Location | LocationLink
): Promise<Location | LocationLink> {
  if (!client) return location

  let uri: Uri
  let range: Range
  const isLocation = 'uri' in location

  // Handle Location or LocationLink
  if (isLocation) {
    // Location
    uri = location.uri
    range = location.range
  } else {
    // LocationLink
    uri = location.targetUri
    range = location.targetRange
  }

  const fsPath = uri.fsPath
  if (fsPath.includes('.pywire')) {
    const workspaceFolder = workspace.getWorkspaceFolder(uri)
    if (workspaceFolder) {
      const rootPath = workspaceFolder.uri.fsPath
      // relPath: pages/counter.wire.py
      const relPath = path.relative(path.join(rootPath, '.pywire'), fsPath)
      const wireRelPath = relPath.slice(0, -3) // remove ".py"
      const wirePath = path.join(rootPath, wireRelPath)
      const wireUri = Uri.file(wirePath)

      try {
        const mapping = (await client.sendRequest('pywire/mapFromGenerated', {
          uri: wireUri.toString(),
          position: range.start,
        })) as PositionMapping | null

        if (mapping) {
          const endMapping = (await client.sendRequest('pywire/mapFromGenerated', {
            uri: wireUri.toString(),
            position: range.end,
          })) as PositionMapping | null

          const startPos = new Position(mapping.line, mapping.character)
          const endPos = endMapping ? new Position(endMapping.line, endMapping.character) : startPos
          const wireRange = new Range(startPos, endPos)

          if (isLocation) {
            return new Location(wireUri, wireRange)
          } else {
            // Return modified LocationLink
            return {
              ...location,
              targetUri: wireUri,
              targetRange: wireRange,
              targetSelectionRange: wireRange,
            }
          }
        }
      } catch (e) {
        console.error('Failed to map location back', e)
      }
    }
  }
  return location
}

export function activate(context: ExtensionContext) {
  extensionDir = context.extensionPath

  const output = window.createOutputChannel('PyWire')
  const log = (message: string) => {
    output.appendLine(`[${new Date().toISOString()}] ${message}`)
  }

  console.log('PyWire extension activating...')
  log('PyWire extension activating')

  // Register context-aware toggle comment command
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
          if (trimmed === '' || isSeparatorLine(lineText)) {
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

  // Get Python path from settings
  const config = workspace.getConfiguration('pywire')
  let pythonPath = config.get<string>('pythonPath')

  // Path to LSP server script (launcher)
  const serverScript = context.asAbsolutePath(path.join('out', 'lsp_launcher.py'))

  console.log('LSP server script:', serverScript)
  log(`LSP server script: ${serverScript}`)

  // Start services asynchronously to allow for python path resolution
  ;(async () => {
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

      // --- Shadow File Logic ---

      // --- Settings & Git Automations ---
      async function ensureHiddenAndIgnored(rootPath: string) {
        // 1. Hide in VS Code
        try {
          const config = workspace.getConfiguration('files')
          const excludes = config.get<{ [key: string]: boolean }>('exclude') || {}
          if (!excludes['**/.pywire']) {
            // Update workspace setting
            await config.update('exclude', { ...excludes, '**/.pywire': true }, 2) // 2 = Workspace
          }
        } catch (e) {
          console.error('Failed to update files.exclude', e)
        }

        // 2. Add to .gitignore (Self-contained)
        try {
          const pywireGitIgnore = path.join(rootPath, '.pywire', '.gitignore')
          // Ensure .pywire exists
          const pywireDir = path.join(rootPath, '.pywire')
          if (!fs.existsSync(pywireDir)) {
            fs.mkdirSync(pywireDir, { recursive: true })
          }

          if (!fs.existsSync(pywireGitIgnore)) {
            fs.writeFileSync(pywireGitIgnore, '*\n')
          }
        } catch (e) {
          console.error('Failed to create .pywire/.gitignore', e)
        }
      }

      async function updateShadowFile(uri: string) {
        if (!client) return

        // Setup directory logic
        const workspaceFolder = workspace.getWorkspaceFolder(Uri.parse(uri))
        if (!workspaceFolder) return

        const rootPath = workspaceFolder.uri.fsPath

        // Ensure hidden/ignored once per session/root?
        // We can just call it safely.
        await ensureHiddenAndIgnored(rootPath)

        try {
          const response = (await client.sendRequest('pywire/virtualCode', {
            uri: uri,
          })) as VirtualCodeResponse | null
          if (response && response.content) {
            // Determine shadow path
            // workspaceRoot/.pywire/relative_path.py
            const workspaceFolder = workspace.getWorkspaceFolder(workspace.workspaceFolders![0].uri)
            if (!workspaceFolder) return

            const rootPath = workspaceFolder.uri.fsPath
            const pywireDir = path.join(rootPath, '.pywire')

            if (!fs.existsSync(pywireDir)) {
              fs.mkdirSync(pywireDir, { recursive: true })
            }

            // Simple flattening or recreating structure?
            // Let's flatten for now: filename.wire -> filename.wire.py
            // But collisions? path_to_file.replace(/[\/\\]/g, '__') could work.
            // But Pylance imports need structure.
            // Ideally we mirror the structure.

            // Get relative path
            const relPath = path.relative(rootPath, Uri.parse(uri).fsPath)
            const shadowRelPath = relPath + '.py'
            const shadowPath = path.join(pywireDir, shadowRelPath)

            const shadowDir = path.dirname(shadowPath)
            if (!fs.existsSync(shadowDir)) {
              fs.mkdirSync(shadowDir, { recursive: true })
            }

            fs.writeFileSync(shadowPath, response.content)
          }
        } catch (e) {
          console.error('Failed to update shadow file', e)
          log(`Failed to update shadow file: ${String(e)}`)
        }
      }

      // --- Middleware ---
      const useBundledPyright = config.get<boolean>('useBundledPyright', false)
      console.log(`Use Bundled Pyright: ${useBundledPyright}`)
      log(`Use Bundled Pyright: ${useBundledPyright}`)

      const middleware = useBundledPyright
        ? undefined
        : {
            provideHover: async (
              document: TextDocument,
              position: Position,
              token: CancellationToken,
              next: ProvideHoverSignature
            ) => {
              // 1. Ask server for mapping
              try {
                const mapping = (await client.sendRequest('pywire/mapToGenerated', {
                  uri: document.uri.toString(),
                  position: position,
                })) as PositionMapping | null

                if (mapping) {
                  // It maps to Python!
                  // 2. Determine shadow URI
                  const workspaceFolder = workspace.getWorkspaceFolder(document.uri)
                  if (workspaceFolder) {
                    const rootPath = workspaceFolder.uri.fsPath
                    const relPath = path.relative(rootPath, document.uri.fsPath)
                    const shadowPath = path.join(rootPath, '.pywire', relPath + '.py')
                    const shadowUri = Uri.file(shadowPath)

                    // Ensure file exists (it should have been updated on change)
                    if (fs.existsSync(shadowPath)) {
                      // 3. Delegate to Pylance
                      const results = await commands.executeCommand<Hover[]>(
                        'vscode.executeHoverProvider',
                        shadowUri,
                        new Position(mapping.line, mapping.character)
                      )

                      if (results && results.length > 0) {
                        return results[0]
                      }
                    }
                  }
                }
              } catch (e) {
                console.error('Hover middleware failed', e)
              }

              // Fallback to default (Jedi)
              return await next(document, position, token)
            },

            provideDefinition: async (
              document: TextDocument,
              position: Position,
              token: CancellationToken,
              next: ProvideDefinitionSignature
            ) => {
              try {
                const mapping = (await client.sendRequest('pywire/mapToGenerated', {
                  uri: document.uri.toString(),
                  position: position,
                })) as PositionMapping | null

                if (mapping) {
                  const workspaceFolder = workspace.getWorkspaceFolder(document.uri)
                  if (workspaceFolder) {
                    const rootPath = workspaceFolder.uri.fsPath
                    const relPath = path.relative(rootPath, document.uri.fsPath)
                    const shadowPath = path.join(rootPath, '.pywire', relPath + '.py')
                    const shadowUri = Uri.file(shadowPath)

                    if (fs.existsSync(shadowPath)) {
                      const results = await commands.executeCommand<
                        Location | LocationLink | (Location | LocationLink)[]
                      >(
                        'vscode.executeDefinitionProvider',
                        shadowUri,
                        new Position(mapping.line, mapping.character)
                      )

                      if (results) {
                        if (Array.isArray(results)) {
                          const mappedResults = await Promise.all(
                            results.map((loc) => mapLocationBack(loc))
                          )
                          // Convert all to LocationLink for middleware signature
                          return mappedResults.filter(Boolean).map((loc) => {
                            if ('uri' in loc) {
                              return {
                                targetUri: loc.uri,
                                targetRange: loc.range,
                                targetSelectionRange: loc.range,
                              } as LocationLink
                            }
                            return loc as LocationLink
                          })
                        } else {
                          const mapped = await mapLocationBack(results)
                          // Convert to LocationLink for middleware signature
                          if ('uri' in mapped) {
                            return [
                              {
                                targetUri: mapped.uri,
                                targetRange: mapped.range,
                                targetSelectionRange: mapped.range,
                              } as LocationLink,
                            ]
                          }
                          return [mapped as LocationLink]
                        }
                      }
                    }
                  }
                }
              } catch (e) {
                console.error('Definition middleware failed', e)
              }
              return await next(document, position, token)
            },

            provideReferences: async (
              document: TextDocument,
              position: Position,
              context: ReferenceContext,
              token: CancellationToken,
              next: ProvideReferencesSignature
            ) => {
              try {
                const mapping = (await client.sendRequest('pywire/mapToGenerated', {
                  uri: document.uri.toString(),
                  position: position,
                })) as PositionMapping | null

                if (mapping) {
                  const workspaceFolder = workspace.getWorkspaceFolder(document.uri)
                  if (workspaceFolder) {
                    const rootPath = workspaceFolder.uri.fsPath
                    const relPath = path.relative(rootPath, document.uri.fsPath)
                    const shadowPath = path.join(rootPath, '.pywire', relPath + '.py')
                    const shadowUri = Uri.file(shadowPath)

                    if (fs.existsSync(shadowPath)) {
                      const results = await commands.executeCommand<Location[]>(
                        'vscode.executeReferenceProvider',
                        shadowUri,
                        new Position(mapping.line, mapping.character)
                      )

                      if (results && Array.isArray(results)) {
                        const mappedResults = await Promise.all(
                          results.map((loc) => mapLocationBack(loc))
                        )
                        // Convert all to Location for middleware signature
                        return mappedResults.filter(Boolean).map((loc) => {
                          if ('uri' in loc) {
                            return loc as Location
                          }
                          // Convert LocationLink to Location
                          return new Location(loc.targetUri, loc.targetRange)
                        })
                      }
                    }
                  }
                }
              } catch (e) {
                console.error('References middleware failed', e)
              }
              return await next(document, position, context, token)
            },

            provideCompletionItem: async (
              document: TextDocument,
              position: Position,
              context: CompletionContext,
              token: CancellationToken,
              next: ProvideCompletionItemsSignature
            ) => {
              try {
                const lines = document.getText().split('\n')
                const section = getSection(lines, position.line)
                log(
                  `Completion request: section=${section} line=${position.line} char=${position.character} lineText="${lines[position.line]?.substring(0, 60)}"`
                )
                if (section === 'separator') {
                  return []
                }

                let mapping: PositionMapping | null = null
                try {
                  mapping = (await client.sendRequest('pywire/mapToGenerated', {
                    uri: document.uri.toString(),
                    position: position,
                  })) as PositionMapping | null
                } catch (e) {
                  console.error('Completion mapping failed', e)
                  log(`Completion mapping failed: ${String(e)}`)
                }

                const usePython = section === 'python' || Boolean(mapping)
                log(`Completion routing: usePython=${usePython}`)
                if (!usePython) {
                  if (!mapping) {
                    log('Completion mapping: null')
                  }
                  return await next(document, position, context, token)
                }
                if (!mapping) {
                  log('Completion mapping: null')
                  return []
                }

                log(`Completion mapping: ${mapping.line}:${mapping.character}`)
                await updateShadowFile(document.uri.toString())

                const workspaceFolder = workspace.getWorkspaceFolder(document.uri)
                if (!workspaceFolder) {
                  return []
                }

                const rootPath = workspaceFolder.uri.fsPath
                const relPath = path.relative(rootPath, document.uri.fsPath)
                const shadowPath = path.join(rootPath, '.pywire', relPath + '.py')
                const shadowUri = Uri.file(shadowPath)

                if (!fs.existsSync(shadowPath)) {
                  return []
                }

                const results = await commands.executeCommand<CompletionList | CompletionItem[]>(
                  'vscode.executeCompletionItemProvider',
                  shadowUri,
                  new Position(mapping.line, mapping.character),
                  context.triggerCharacter
                )
                if (!results) {
                  log('Completion results: empty')
                  return []
                }

                // Get prefix from wire file for filterText adjustment
                const lineText = document.lineAt(position.line).text
                const prefixMatch = lineText.slice(0, position.character).match(/[\w.$]*$/)
                const wirePrefix = prefixMatch ? prefixMatch[0] : ''
                log(`Completion prefix: "${wirePrefix}"`)

                const stripEdits = (item: CompletionItem) => {
                  return {
                    ...item,
                    // Clear filterText to let VS Code use label directly
                    filterText: undefined,
                    sortText: item.sortText,
                    textEdit: undefined,
                    additionalTextEdits: undefined,
                    range: undefined,
                  }
                }

                if (Array.isArray(results)) {
                  log(`Completion results: ${results.length} items (array)`)
                  return results.map(stripEdits)
                }
                if (results.items && Array.isArray(results.items)) {
                  log(`Completion results: ${results.items.length} items (list)`)
                  return {
                    ...results,
                    items: results.items.map(stripEdits),
                  }
                }

                log('Completion results: non-list result')
                return results
              } catch (e) {
                console.error('Completion middleware failed', e)
                log(`Completion middleware failed: ${String(e)}`)
              }
              return []
            },

            // Add handleDiagnostics to trigger shadow update?
            // Or just listen to change events.
          }

      // Client options - what to send to the server
      const clientOptions: LanguageClientOptions = {
        documentSelector: [{ scheme: 'file', language: 'pywire' }],
        synchronize: {
          fileEvents: workspace.createFileSystemWatcher('**/*.pywire'),
        },
        middleware: middleware,
        initializationOptions: {
          useBundledPyright: useBundledPyright,
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

      // Listen for document changes to update shadow files
      workspace.onDidChangeTextDocument(async (e) => {
        if (e.document.languageId === 'pywire') {
          // Debounce?
          await updateShadowFile(e.document.uri.toString())
        }
      })

      // Also on initial open/startup for visible editors
      window.visibleTextEditors.forEach((editor) => {
        if (editor.document.languageId === 'pywire') {
          updateShadowFile(editor.document.uri.toString())
        }
      })

      // On open
      workspace.onDidOpenTextDocument(async (doc) => {
        if (doc.languageId === 'pywire') {
          await updateShadowFile(doc.uri.toString())
        }
      })

      window.showInformationMessage('PyWire services are running')
    } catch (err) {
      console.error('Failed to start PyWire services:', err)
      window.showErrorMessage('Failed to start PyWire services: ' + err)
      log(`Failed to start PyWire services: ${String(err)}`)
    }
  })()
}

export function deactivate(): Promise<void> | undefined {
  if (!client) {
    return undefined
  }
  return client.stop()
}
