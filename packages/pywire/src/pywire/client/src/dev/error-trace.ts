import { StackFrame } from '../core/transports';

/**
 * Handles error traces from the server in development mode.
 * Loads source files and displays errors with proper source mapping in DevTools.
 */
export class ErrorTraceHandler {
    private loadedSources = new Set<string>();

    /**
     * Get a virtual URL for a filename that Chrome will display in stack traces.
     */
    private getVirtualUrl(filename: string): string {
        const encoded = btoa(filename).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
        const cleanName = filename.split(/[/\\]/).pop() || 'unknown';
        return `${window.location.origin}/_pywire/file/${encoded}/${cleanName}`;
    }

    /**
     * Handle an error trace message from the server.
     */
    async handle(errorMessage: string, trace: StackFrame[]): Promise<void> {
        // Load sources for frames
        const filesToLoad = new Set<string>();
        for (const frame of trace) {
            if (!this.loadedSources.has(frame.filename)) {
                filesToLoad.add(frame.filename);
            }
        }

        await Promise.all(Array.from(filesToLoad).map(async (filename) => {
            try {
                const virtualUrl = this.getVirtualUrl(filename);

                // Fetch content
                const url = `/_pywire/source?path=${encodeURIComponent(filename)}`;
                const resp = await fetch(url);
                if (resp.ok) {
                    const content = await resp.text();

                    // Inject the raw source with sourceURL for DevTools
                    const sourceCode = `${content}\n//# sourceURL=${virtualUrl}`;
                    try {
                        // @ts-ignore - indirect eval for global scope
                        (0, eval)(sourceCode);
                    } catch {
                        // Syntax errors from Python content are expected - ignore
                    }

                    this.loadedSources.add(filename);
                }

                this.loadedSources.add(filename);
            } catch (e) {
                console.warn('PyWire: Failed to load source', filename, e);
            }
        }));

        // Construct Error with stack pointing to virtual URLs
        const err = new Error(errorMessage);
        const stackLines = [`${err.name}: ${err.message}`];

        for (const frame of trace) {
            const fn = frame.name || '<module>';
            const virtualUrl = this.getVirtualUrl(frame.filename);
            const col = frame.colno ?? 1;
            stackLines.push(`    at ${fn} (${virtualUrl}:${frame.lineno}:${col})`);
        }

        err.stack = stackLines.join('\n');

        // Log just the stack string to avoid Chrome appending its own call stack
        console.error(err.stack);
    }
}
