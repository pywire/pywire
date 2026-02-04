import React, { useEffect, useRef, useState } from 'react';

// Monkey-patch Worker to handle the "Module scripts don't support importScripts()" error
if (typeof window !== 'undefined' && !(window as any).__workerPatched) {
    const OriginalWorker = window.Worker;
    (window as any).Worker = function (url: string | URL, options?: WorkerOptions) {
        const urlStr = typeof url === 'string' ? url : url.toString();
        // Force classic type for all blob workers that try to be modules
        if (urlStr.startsWith('blob:') && options?.type === 'module') {
            return new OriginalWorker(url, { ...options, type: 'classic' });
        }
        return new OriginalWorker(url, options);
    } as any;
    (window as any).__workerPatched = true;
}

interface EditorProps {
    content: string;
    language: string;
    onChange?: (value: string) => void;
}

// Initialize Monaco environment for workers (once)
function setupMonacoEnvironment(monaco: any) {
    if (typeof window === 'undefined' || (window as any).MonacoEnvironment) return;

    (window as any).MonacoEnvironment = {
        getWorkerUrl: function (_moduleId: any, label: string) {
            const baseUrl = import.meta.env.BASE_URL.endsWith('/')
                ? import.meta.env.BASE_URL
                : `${import.meta.env.BASE_URL}/`;

            const origin = window.location.origin;
            const fullBaseUrl = `${origin}${baseUrl}`;

            const workerUrlMap: Record<string, string> = {
                json: `${fullBaseUrl}workers/json.worker.js`,
                css: `${fullBaseUrl}workers/css.worker.js`,
                scss: `${fullBaseUrl}workers/css.worker.js`,
                less: `${fullBaseUrl}workers/css.worker.js`,
                html: `${fullBaseUrl}workers/html.worker.js`,
                handlebars: `${fullBaseUrl}workers/html.worker.js`,
                razor: `${fullBaseUrl}workers/html.worker.js`,
                typescript: `${fullBaseUrl}workers/ts.worker.js`,
                javascript: `${fullBaseUrl}workers/ts.worker.js`,
            };
            const workerUrl = workerUrlMap[label] || `${fullBaseUrl}workers/editor.worker.js`;

            // Cross-origin worker wrapper using classic worker (importScripts)
            const blob = new Blob([
                `self.MonacoEnvironment = { baseUrl: '${fullBaseUrl}' };
                 importScripts('${workerUrl}');`
            ], { type: 'application/javascript' });
            return URL.createObjectURL(blob);
        }
    };
}

// Singleton for Shiki highligher to avoid multiple initializations
let highlighterInstance: any = null;
let highlighterPromise: Promise<any> | null = null;

export const Editor: React.FC<EditorProps> = ({ content, language, onChange }) => {
    const editorRef = useRef<HTMLDivElement>(null);
    const monacoInstanceRef = useRef<any>(null);
    const editorInstanceRef = useRef<any>(null);
    const [isLoaded, setIsLoaded] = useState(false);

    useEffect(() => {
        let editor: any;
        let observer: MutationObserver;

        async function init() {
            if (!editorRef.current) return;

            // Dynamically import monaco-editor and shiki to avoid SSR issues
            const [monaco, { createHighlighter }, { shikiToMonaco }] = await Promise.all([
                import('monaco-editor'),
                import('shiki'),
                import('@shikijs/monaco')
            ]);

            monacoInstanceRef.current = monaco;

            // Register PyWire language in Monaco if not already done
            if (!monaco.languages.getLanguages().some(lang => lang.id === 'pywire')) {
                monaco.languages.register({
                    id: 'pywire',
                    extensions: ['.wire'],
                    aliases: ['PyWire', 'pywire'],
                });
            }

            // Initialize Shiki if not already done
            if (!highlighterInstance) {
                if (!highlighterPromise) {
                    highlighterPromise = (async () => {
                        const baseUrl = (import.meta.env.BASE_URL || '/').endsWith('/')
                            ? (import.meta.env.BASE_URL || '/')
                            : `${import.meta.env.BASE_URL}/`;

                        const fullBaseUrl = `${window.location.origin}${baseUrl}`;
                        const grammarUrl = `${fullBaseUrl}grammars/pywire.tmLanguage.json`;

                        let pywireGrammar = null;
                        try {
                            const response = await fetch(grammarUrl);
                            if (response.ok) {
                                pywireGrammar = await response.json();
                            }
                        } catch (e) {
                            console.error('Error fetching PyWire grammar:', e);
                        }

                        const langs: any[] = ['python', 'html', 'css', 'javascript', 'json', 'typescript'];
                        if (pywireGrammar) {
                            langs.push({
                                ...pywireGrammar,
                                name: 'pywire',
                            });
                        }

                        const highlighter = await createHighlighter({
                            themes: ['catppuccin-mocha', 'catppuccin-latte'],
                            langs: langs,
                        });

                        shikiToMonaco(highlighter, monaco);
                        highlighterInstance = highlighter;
                        return highlighter;
                    })();
                }
                await highlighterPromise;
            }

            setupMonacoEnvironment(monaco);

            const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
            const theme = isDark ? 'catppuccin-mocha' : 'catppuccin-latte';
            const monacoLanguage = language === 'pywire' ? 'pywire' : language;

            editor = monaco.editor.create(editorRef.current, {
                value: content,
                language: monacoLanguage,
                theme: theme,
                automaticLayout: true,
                minimap: { enabled: false },
                fontSize: 14,
                lineNumbers: 'on',
                scrollBeyondLastLine: false,
                roundedSelection: false,
                padding: { top: 10 },
            });

            editorInstanceRef.current = editor;
            setIsLoaded(true);

            editor.onDidChangeModelContent(() => {
                onChange?.(editor.getValue());
            });

            // Watch for theme changes from Starlight
            observer = new MutationObserver((mutations) => {
                mutations.forEach((mutation) => {
                    const newTheme = document.documentElement.getAttribute('data-theme');
                    monaco.editor.setTheme(newTheme === 'light' ? 'catppuccin-latte' : 'catppuccin-mocha');
                });
            });

            observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
        }

        init();

        return () => {
            if (observer) observer.disconnect();
            if (editor) editor.dispose();
        };
    }, []);

    useEffect(() => {
        if (editorInstanceRef.current && editorInstanceRef.current.getValue() !== content) {
            editorInstanceRef.current.setValue(content);
        }
    }, [content]);

    return <div ref={editorRef} style={{ height: '100%', width: '100%' }} />;
};
