import * as path from 'path';
import {
    workspace, ExtensionContext, window, commands, Selection, Position, Range,
    TextEditor, TextEditorEdit, languages, extensions, Uri, TextDocument, CancellationToken, Hover,
    Location, LocationLink, CompletionItem, CompletionList, ProviderResult
} from 'vscode';
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
    ProvideHoverSignature
} from 'vscode-languageclient/node';

let client: LanguageClient;

/**
 * Determine which section a line is in based on the --- separator.
 * Returns 'python' for lines after ---, 'directive' for lines starting with ! or #!,
 * 'separator' for the --- line, 'html' for HTML content lines.
 */
function getSection(lines: string[], lineNumber: number): 'python' | 'directive' | 'html' | 'separator' {
    let separatorLine = -1;
    for (let i = 0; i < lines.length; i++) {
        if (lines[i].trim() === '---') {
            separatorLine = i;
            break;
        }
    }

    if (lineNumber === separatorLine) {
        return 'separator';
    }

    if (separatorLine !== -1 && lineNumber > separatorLine) {
        return 'python';
    }

    const lineText = lines[lineNumber]?.trim() || '';
    // Check for directive or commented directive
    if (lineText.startsWith('!') || lineText.startsWith('# !') || lineText.startsWith('#!')) {
        return 'directive';
    }

    return 'html';
}

/**
 * Detect what type of comment (if any) is on a line.
 * Returns 'python' for # comments, 'html' for <!-- --> comments, or null for no comment.
 */
function detectExistingComment(line: string): 'python' | 'html' | null {
    const trimmed = line.trim();
    if (trimmed.startsWith('<!--') && trimmed.endsWith('-->')) {
        return 'html';
    }
    if (trimmed.startsWith('#')) {
        return 'python';
    }
    return null;
}

/**
 * Remove comment from a line based on detected comment type.
 */
function removeComment(line: string, commentType: 'python' | 'html'): string {
    if (commentType === 'python') {
        // Remove # comment, preserving indent
        return line.replace(/^(\s*)# ?/, '$1');
    } else {
        // Remove <!-- --> comment, preserving indent
        const match = line.match(/^(\s*)<!--\s?(.*?)\s?-->(\s*)$/);
        if (match) {
            return match[1] + match[2];
        }
        return line;
    }
}

/**
 * Add comment to a line based on section type.
 */
function addComment(line: string, section: 'python' | 'directive' | 'html'): string {
    const match = line.match(/^(\s*)/);
    const indent = match ? match[1] : '';
    const content = line.trimStart();

    if (section === 'python' || section === 'directive') {
        return indent + '# ' + content;
    } else {
        return indent + '<!-- ' + content + ' -->';
    }
}

/**
 * Map a location from a shadow .py file back to the original .wire file.
 */
async function mapLocationBack(location: any): Promise<any> {
    if (!client) return location;

    let uri: Uri;
    let range: Range;

    // Handle Location or LocationLink
    if (location.uri) {
        // Location
        uri = location.uri;
        range = location.range;
    } else if (location.targetUri) {
        // LocationLink
        uri = location.targetUri;
        range = location.targetRange;
    } else {
        return location;
    }

    const fsPath = uri.fsPath;
    if (fsPath.includes('.pywire')) {
        const workspaceFolder = workspace.getWorkspaceFolder(uri);
        if (workspaceFolder) {
            const rootPath = workspaceFolder.uri.fsPath;
            // relPath: pages/counter.wire.py
            const relPath = path.relative(path.join(rootPath, '.pywire'), fsPath);
            const wireRelPath = relPath.slice(0, -3); // remove ".py"
            const wirePath = path.join(rootPath, wireRelPath);
            const wireUri = Uri.file(wirePath);

            try {
                const mapping: any = await client.sendRequest('pywire/mapFromGenerated', {
                    uri: wireUri.toString(),
                    position: range.start
                });

                if (mapping) {
                    const endMapping: any = await client.sendRequest('pywire/mapFromGenerated', {
                        uri: wireUri.toString(),
                        position: range.end
                    });

                    const startPos = new Position(mapping.line, mapping.character);
                    const endPos = endMapping ? new Position(endMapping.line, endMapping.character) : startPos;
                    const wireRange = new Range(startPos, endPos);

                    if (location.uri) {
                        return new Location(wireUri, wireRange);
                    } else {
                        // Return modified LocationLink
                        return {
                            ...location,
                            targetUri: wireUri,
                            targetRange: wireRange,
                            targetSelectionRange: wireRange
                        };
                    }
                }
            } catch (e) {
                console.error('Failed to map location back', e);
            }
        }
    }
    return location;
}

export function activate(context: ExtensionContext) {
    console.log('PyWire extension activating...');

    // Register context-aware toggle comment command
    const toggleCommentCmd = commands.registerTextEditorCommand(
        'pywire.toggleComment',
        (editor: TextEditor, edit: TextEditorEdit) => {
            const document = editor.document;
            if (document.languageId !== 'pywire') {
                // Fall back to default comment command for non-pywire files
                commands.executeCommand('editor.action.commentLine');
                return;
            }

            const lines = document.getText().split('\n');
            const selections = editor.selections;

            for (const selection of selections) {
                const startLine = selection.start.line;
                const endLine = selection.end.line;

                for (let lineNum = startLine; lineNum <= endLine; lineNum++) {
                    const lineText = document.lineAt(lineNum).text;
                    const trimmed = lineText.trim();

                    // Skip empty lines and separator
                    if (trimmed === '' || trimmed === '---') {
                        continue;
                    }

                    // Determine section for THIS line
                    const section = getSection(lines, lineNum);
                    if (section === 'separator') {
                        continue;
                    }

                    // Check if line already has a comment
                    const existingComment = detectExistingComment(lineText);

                    let newText: string;
                    if (existingComment) {
                        // Remove existing comment
                        newText = removeComment(lineText, existingComment);
                    } else {
                        // Add comment based on section
                        newText = addComment(lineText, section);
                    }

                    const lineRange = document.lineAt(lineNum).range;
                    edit.replace(lineRange, newText);
                }
            }
        }
    );
    context.subscriptions.push(toggleCommentCmd);

    // Get Python path from settings
    const config = workspace.getConfiguration('pywire');
    let pythonPath = config.get<string>('pythonPath');

    // Path to LSP server script (launcher)
    const serverScript = context.asAbsolutePath(
        path.join('src', 'lsp_launcher.py')
    );

    console.log('LSP server script:', serverScript);


    // Start services asynchronously to allow for python path resolution
    (async () => {
        try {
            // If no explicit path set, try to get it from the Python extension
            if (!pythonPath) {
                const pythonExtension = extensions.getExtension('ms-python.python');
                if (pythonExtension) {
                    if (!pythonExtension.isActive) {
                        await pythonExtension.activate();
                    }
                    const exports = pythonExtension.exports;
                    // Use the public API to get the execution details
                    if (exports.settings && exports.settings.getExecutionDetails) {
                        const executionDetails = exports.settings.getExecutionDetails(workspace.workspaceFolders?.[0]?.uri);
                        pythonPath = executionDetails?.execCommand?.[0];
                    }
                }
            }

            if (!pythonPath) {
                // Last resort fallback
                pythonPath = 'python3';
            }
            console.log(`Using Python interpreter: ${pythonPath}`);

            // Server options - how to start the server
            const serverOptions: ServerOptions = {
                command: pythonPath,
                args: [serverScript],
                options: {
                    env: { ...process.env }
                }
            };

            // --- Shadow File Logic ---
            const fs = require('fs');


            // --- Settings & Git Automations ---
            async function ensureHiddenAndIgnored(rootPath: string) {
                // 1. Hide in VS Code
                try {
                    const config = workspace.getConfiguration('files');
                    const excludes = config.get<{ [key: string]: boolean }>('exclude') || {};
                    if (!excludes['**/.pywire']) {
                        // Update workspace setting
                        await config.update('exclude', { ...excludes, '**/.pywire': true }, 2); // 2 = Workspace
                    }
                } catch (e) {
                    console.error('Failed to update files.exclude', e);
                }

                // 2. Add to .gitignore (Self-contained)
                try {
                    const pywireGitIgnore = path.join(rootPath, '.pywire', '.gitignore');
                    // Ensure .pywire exists
                    const pywireDir = path.join(rootPath, '.pywire');
                    if (!fs.existsSync(pywireDir)) {
                        fs.mkdirSync(pywireDir, { recursive: true });
                    }

                    if (!fs.existsSync(pywireGitIgnore)) {
                        fs.writeFileSync(pywireGitIgnore, '*\n');
                    }
                } catch (e) {
                    console.error('Failed to create .pywire/.gitignore', e);
                }
            }

            async function updateShadowFile(uri: string) {
                if (!client) return;

                // Setup directory logic
                const workspaceFolder = workspace.getWorkspaceFolder(Uri.parse(uri));
                if (!workspaceFolder) return;

                const rootPath = workspaceFolder.uri.fsPath;

                // Ensure hidden/ignored once per session/root? 
                // We can just call it safely.
                await ensureHiddenAndIgnored(rootPath);

                try {
                    const response: any = await client.sendRequest('pywire/virtualCode', { uri: uri });
                    if (response && response.content) {
                        // Determine shadow path
                        // workspaceRoot/.pywire/relative_path.py
                        const workspaceFolder = workspace.getWorkspaceFolder(workspace.workspaceFolders![0].uri);
                        if (!workspaceFolder) return;

                        const rootPath = workspaceFolder.uri.fsPath;
                        const pywireDir = path.join(rootPath, '.pywire');

                        if (!fs.existsSync(pywireDir)) {
                            fs.mkdirSync(pywireDir, { recursive: true });
                        }

                        // Simple flattening or recreating structure?
                        // Let's flatten for now: filename.wire -> filename.wire.py
                        // But collisions? path_to_file.replace(/[\/\\]/g, '__') could work.
                        // But Pylance imports need structure.
                        // Ideally we mirror the structure.

                        // Get relative path
                        const relPath = path.relative(rootPath, Uri.parse(uri).fsPath);
                        const shadowRelPath = relPath + ".py";
                        const shadowPath = path.join(pywireDir, shadowRelPath);

                        const shadowDir = path.dirname(shadowPath);
                        if (!fs.existsSync(shadowDir)) {
                            fs.mkdirSync(shadowDir, { recursive: true });
                        }

                        fs.writeFileSync(shadowPath, response.content);
                    }
                } catch (e) {
                    console.error('Failed to update shadow file', e);
                }
            }

            // --- Middleware ---
            const useBundledPyright = config.get<boolean>('useBundledPyright', false);
            console.log(`Use Bundled Pyright: ${useBundledPyright}`);

            const middleware = useBundledPyright ? undefined : {
                provideHover: async (document: TextDocument, position: Position, token: CancellationToken, next: ProvideHoverSignature) => {
                    // 1. Ask server for mapping
                    try {
                        const mapping: any = await client.sendRequest('pywire/mapToGenerated', {
                            uri: document.uri.toString(),
                            position: position
                        });

                        if (mapping) {
                            // It maps to Python!
                            // 2. Determine shadow URI
                            const workspaceFolder = workspace.getWorkspaceFolder(document.uri);
                            if (workspaceFolder) {
                                const rootPath = workspaceFolder.uri.fsPath;
                                const relPath = path.relative(rootPath, document.uri.fsPath);
                                const shadowPath = path.join(rootPath, '.pywire', relPath + ".py");
                                const shadowUri = Uri.file(shadowPath);

                                // Ensure file exists (it should have been updated on change)
                                if (fs.existsSync(shadowPath)) {
                                    // 3. Delegate to Pylance
                                    const results = await commands.executeCommand<Hover[]>(
                                        'vscode.executeHoverProvider',
                                        shadowUri,
                                        new Position(mapping.line, mapping.character)
                                    );

                                    if (results && results.length > 0) {
                                        return results[0];
                                    }
                                }
                            }
                        }
                    } catch (e) {
                        console.error('Hover middleware failed', e);
                    }

                    // Fallback to default (Jedi)
                    return await next(document, position, token);
                },

                provideDefinition: async (document: TextDocument, position: Position, token: CancellationToken, next: any) => {
                    try {
                        const mapping: any = await client.sendRequest('pywire/mapToGenerated', {
                            uri: document.uri.toString(),
                            position: position
                        });

                        if (mapping) {
                            const workspaceFolder = workspace.getWorkspaceFolder(document.uri);
                            if (workspaceFolder) {
                                const rootPath = workspaceFolder.uri.fsPath;
                                const relPath = path.relative(rootPath, document.uri.fsPath);
                                const shadowPath = path.join(rootPath, '.pywire', relPath + ".py");
                                const shadowUri = Uri.file(shadowPath);

                                if (fs.existsSync(shadowPath)) {
                                    const results = await commands.executeCommand<any>(
                                        'vscode.executeDefinitionProvider',
                                        shadowUri,
                                        new Position(mapping.line, mapping.character)
                                    );

                                    if (results) {
                                        if (Array.isArray(results)) {
                                            const mappedResults = await Promise.all(results.map(loc => mapLocationBack(loc)));
                                            return mappedResults.filter(Boolean);
                                        } else {
                                            return await mapLocationBack(results);
                                        }
                                    }
                                }
                            }
                        }
                    } catch (e) {
                        console.error('Definition middleware failed', e);
                    }
                    return await next(document, position, token);
                },

                provideReferences: async (document: TextDocument, position: Position, context: any, token: CancellationToken, next: any) => {
                    try {
                        const mapping: any = await client.sendRequest('pywire/mapToGenerated', {
                            uri: document.uri.toString(),
                            position: position
                        });

                        if (mapping) {
                            const workspaceFolder = workspace.getWorkspaceFolder(document.uri);
                            if (workspaceFolder) {
                                const rootPath = workspaceFolder.uri.fsPath;
                                const relPath = path.relative(rootPath, document.uri.fsPath);
                                const shadowPath = path.join(rootPath, '.pywire', relPath + ".py");
                                const shadowUri = Uri.file(shadowPath);

                                if (fs.existsSync(shadowPath)) {
                                    const results = await commands.executeCommand<any[]>(
                                        'vscode.executeReferenceProvider',
                                        shadowUri,
                                        new Position(mapping.line, mapping.character)
                                    );

                                    if (results && Array.isArray(results)) {
                                        const mappedResults = await Promise.all(results.map(loc => mapLocationBack(loc)));
                                        return mappedResults.filter(Boolean);
                                    }
                                }
                            }
                        }
                    } catch (e) {
                        console.error('References middleware failed', e);
                    }
                    return await next(document, position, context, token);
                },

                provideCompletionItems: async (document: TextDocument, position: Position, context: any, token: CancellationToken, next: any) => {
                    try {
                        const mapping: any = await client.sendRequest('pywire/mapToGenerated', {
                            uri: document.uri.toString(),
                            position: position
                        });

                        if (mapping) {
                            const workspaceFolder = workspace.getWorkspaceFolder(document.uri);
                            if (workspaceFolder) {
                                const rootPath = workspaceFolder.uri.fsPath;
                                const relPath = path.relative(rootPath, document.uri.fsPath);
                                const shadowPath = path.join(rootPath, '.pywire', relPath + ".py");
                                const shadowUri = Uri.file(shadowPath);

                                if (fs.existsSync(shadowPath)) {
                                    const results = await commands.executeCommand<any>(
                                        'vscode.executeCompletionItemProvider',
                                        shadowUri,
                                        new Position(mapping.line, mapping.character),
                                        context.triggerCharacter
                                    );
                                    return results;
                                }
                            }
                        }
                    } catch (e) {
                        console.error('Completion middleware failed', e);
                    }
                    return await next(document, position, context, token);
                }

                // Add handleDiagnostics to trigger shadow update?
                // Or just listen to change events.
            };

            // Client options - what to send to the server
            const clientOptions: LanguageClientOptions = {
                documentSelector: [
                    { scheme: 'file', language: 'pywire' }
                ],
                synchronize: {
                    fileEvents: workspace.createFileSystemWatcher('**/*.pywire')
                },
                middleware: middleware,
                initializationOptions: {
                    useBundledPyright: useBundledPyright
                }
            };

            // Create the language client
            client = new LanguageClient(
                'pywireLanguageServer',
                'PyWire Language Server',
                serverOptions,
                clientOptions
            );

            await client.start();
            console.log('PyWire language server started');

            // Listen for document changes to update shadow files
            workspace.onDidChangeTextDocument(async (e) => {
                if (e.document.languageId === 'pywire') {
                    // Debounce?
                    await updateShadowFile(e.document.uri.toString());
                }
            });

            // Also on initial open/startup for visible editors
            window.visibleTextEditors.forEach(editor => {
                if (editor.document.languageId === 'pywire') {
                    updateShadowFile(editor.document.uri.toString());
                }
            });

            // On open
            workspace.onDidOpenTextDocument(async (doc) => {
                if (doc.languageId === 'pywire') {
                    await updateShadowFile(doc.uri.toString());
                }
            });

            window.showInformationMessage('PyWire services are running');
        } catch (err) {
            console.error('Failed to start PyWire services:', err);
            window.showErrorMessage('Failed to start PyWire services: ' + err);
        }
    })();
}

export function deactivate(): Thenable<void> | undefined {
    if (!client) {
        return undefined;
    }
    return client.stop();
}