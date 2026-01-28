import * as path from 'path';
import { workspace, ExtensionContext, window, commands, Selection, Position, Range, TextEditor, TextEditorEdit, languages } from 'vscode';
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
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
    // HARDCODED for testing: use the project's venv python
    const pythonPath = '/Users/rholmdahl/projects/pywire/.venv/bin/python';
    // const pythonPath = config.get<string>('pythonPath') || 'python3';

    // Path to LSP server script
    // Assumes lsp/ is adjacent to vscode-pywire/
    const serverScript = context.asAbsolutePath(
        path.join('..', 'lsp', 'pywire_lsp_server')
    );

    console.log('LSP server script:', serverScript);

    // #region agent log
    fetch('http://127.0.0.1:7243/ingest/41df94cc-62d1-43cd-920c-d1dbf5d35a88', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ location: 'vscode-pywire/src/extension.ts:26', message: 'Extension activating, server options', data: { pythonPath, serverScript }, timestamp: Date.now(), sessionId: 'debug-session', hypothesisId: 'H1' }) }).catch(() => { });
    // #endregion

    // Server options - how to start the server
    const serverOptions: ServerOptions = {
        command: pythonPath,
        args: [serverScript],
        options: {
            env: { ...process.env }
        }
    };

    // Client options - what to send to the server
    const clientOptions: LanguageClientOptions = {
        documentSelector: [
            { scheme: 'file', language: 'pywire' }
        ],
        synchronize: {
            fileEvents: workspace.createFileSystemWatcher('**/*.pywire')
        },
        // Enable semantic tokens
        initializationOptions: {}
    };

    // Create the language client
    client = new LanguageClient(
        'pywireLanguageServer',
        'PyWire Language Server',
        serverOptions,
        clientOptions
    );

    // Start services
    (async () => {
        try {
            await client.start();
            console.log('PyWire language server started');

            // Initialize Tree-sitter
            const { TreeSitterService } = await import('./syntax/TreeSitterService');
            const { PyWireSemanticTokenProvider, legend } = await import('./syntax/PyWireSemanticTokenProvider');

            const treeSitterService = new TreeSitterService(context);
            await treeSitterService.init();

            const semanticProvider = new PyWireSemanticTokenProvider(treeSitterService);

            context.subscriptions.push(
                languages.registerDocumentSemanticTokensProvider(
                    { language: 'pywire', scheme: 'file' },
                    semanticProvider,
                    legend
                )
            );

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