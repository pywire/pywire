import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Panel, Group, Separator } from 'react-resizable-panels';
import { Editor } from './Editor';
import { BrowserPreview } from './BrowserPreview';
import { TutorialFileTree } from './tree/TutorialFileTree';
import { LoadingSpinner } from './LoadingSpinner';
import { TutorialEngine } from './TutorialEngine';
import { useTutorialStorage } from '../../hooks/useTutorialStorage';
import { ChevronLeft, ChevronRight, Menu, Wrench, ArrowLeft, ArrowRight } from 'lucide-react';

import '../../styles/pywire-tutorial.css';

const DEBUG_TUTORIAL = false;

interface TutorialWorkspaceProps {
    stepId: string;
    title: string;
    stepNumber?: number;
    initialCode: string;
    files?: string[];
    nextStep?: { slug: string; title: string };
    prevStep?: { slug: string; title: string };
    children?: React.ReactNode;
}

export const TutorialWorkspace: React.FC<TutorialWorkspaceProps> = ({
    stepId,
    title,
    stepNumber,
    initialCode,
    files = ['index.wire'],
    nextStep,
    prevStep,
    children
}) => {
    // Persistence: engineRef stays alive across props changes because the component stays mounted
    const engineRef = useRef<TutorialEngine | null>(null);
    const [isReady, setIsReady] = useState(false);
    const [loadingMessage, setLoadingMessage] = useState('Initializing Pyodide...');
    const [theme, setTheme] = useState<'light' | 'dark'>('dark');

    // Code state - using step-specific storage
    const [code, setCode] = useTutorialStorage(stepId, initialCode);
    const [activeFile, setActiveFile] = useState(files[0]);
    const debouncedCode = useDebounce(code, 600);

    // Re-initialize code when step changes (if not already in storage)
    useEffect(() => {
        setActiveFile(files[0]);
        if (isReady && engineRef.current) {
            engineRef.current.reset();
        }
    }, [stepId, files, isReady]);

    const handlePreviewMessage = (msg: any) => {
        if (!engineRef.current) return;
        switch (msg.type) {
            case 'WS_CONNECT': engineRef.current.wsConnect(msg.payload.path); break;
            case 'WS_SEND': engineRef.current.wsSend(msg.payload.data); break;
            case 'HTTP_REQUEST': engineRef.current.httpRequest(msg.payload.method, msg.payload.path, msg.payload.headers); break;
        }
    };

    // Initialize engine once
    useEffect(() => {
        // Register Service Worker
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.register('/docs/sw.js')
                .then(reg => console.log('[Tutorial] Service Worker registered:', reg.scope))
                .catch(err => console.warn('[Tutorial] Service Worker registration failed:', err));
        }

        if (!engineRef.current) {
            engineRef.current = new TutorialEngine({
                onReady: () => setIsReady(true),
                onResponse: (data) => {
                    if (data.type === 'http_response' && data.message.type === 'http.response.body') {
                        const body = data.message.body;
                        const html = Array.isArray(body) ? new TextDecoder().decode(new Uint8Array(body)) : body;
                        (window as any).__PYWIRE_UPDATE_PREVIEW__?.(html);
                    }
                    else if (data.type === 'ws_message') {
                        (window as any).__PYWIRE_SEND_TO_PREVIEW__?.(data);
                    }
                },
                onLog: (msg) => {
                    if (!isReady) {
                        const cleanMsg = msg.replace(/\u001b\[\d+m/g, '');
                        setLoadingMessage(cleanMsg);
                    }
                }
            });
        }

        // Handle theme sync with Starlight/system
        const initialTheme = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
        setTheme(initialTheme);

        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.type === 'attributes' && mutation.attributeName === 'data-theme') {
                    setTheme(document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark');
                }
            });
        });
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

        return () => observer.disconnect();
    }, []);

    // Push updates to engine when code or file changes
    useEffect(() => {
        if (isReady && engineRef.current) {
            engineRef.current.updateFile(activeFile, debouncedCode);
            engineRef.current.httpRequest('GET', '/');
        }
    }, [isReady, debouncedCode, activeFile]);

    const toggleTheme = () => {
        const newTheme = theme === 'light' ? 'dark' : 'light';
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('starlight-theme', newTheme);
        setTheme(newTheme);
    };

    if (!isReady) {
        return (
            <div className="flex items-center justify-center h-full w-full">
                <LoadingSpinner message={loadingMessage} />
            </div>
        );
    }

    return (
        <div className="pw-workspace-container bg-[#03060a]">
            {/* Refined Header inspired by Svelte Tutorial */}
            <header className="pw-header">
                <div className="pw-header-group">
                    <button className="pw-btn-icon-sm" title="Menu">
                        <Menu size={18} />
                    </button>
                    <div className="flex items-center gap-1 ml-2">
                        {prevStep ? (
                            <a href={`/docs/tutorial/${prevStep.slug}`} className="pw-btn-icon-sm" title={`Previous: ${prevStep.title}`}>
                                <ArrowLeft size={18} />
                            </a>
                        ) : (
                            <div className="pw-btn-icon-sm disabled">
                                <ArrowLeft size={18} />
                            </div>
                        )}
                        {nextStep ? (
                            <a href={`/docs/tutorial/${nextStep.slug}`} className="pw-btn-icon-sm" title={`Next: ${nextStep.title}`}>
                                <ArrowRight size={18} />
                            </a>
                        ) : (
                            <div className="pw-btn-icon-sm disabled">
                                <ArrowRight size={18} />
                            </div>
                        )}
                    </div>

                    <div className="pw-breadcrumb ml-4">
                        <span className="pw-breadcrumb-prefix">PyWire Tutorial</span>
                        <span className="pw-breadcrumb-separator">/</span>
                        <span className="pw-breadcrumb-title">{title}</span>
                    </div>
                </div>

                <div className="pw-header-group">
                    <button className="pw-btn-solve mr-2">
                        solve
                    </button>
                    <button className="pw-btn-icon-sm">
                        <Wrench size={18} />
                    </button>
                </div>
            </header>

            <div className="pw-workspace-main">
                <Group orientation="horizontal" className="h-full">
                    {/* Left: Instructions */}
                    <Panel defaultSize={"30%"} minSize={"20%"} className="h-full border-r border-[var(--sl-color-border)] bg-[var(--sl-color-bg)]">
                        <div className="h-full overflow-y-auto pw-instructions-container">
                            <div className="prose prose-sm dark:prose-invert max-w-none">
                                {children}
                            </div>
                        </div>
                    </Panel>

                    <Separator className="pw-separator-h" />

                    {/* Right: Work Area (Split Top/Bottom) */}
                    <Panel defaultSize={"70%"} minSize={"40%"} className="h-full">
                        <Group orientation="vertical" className="h-full">
                            {/* Top: Files + Editor */}
                            <Panel defaultSize={"50%"} minSize={"25%"} className="h-full flex flex-col">
                                <Group orientation="horizontal" className="flex-1 min-h-0">
                                    <Panel defaultSize={"20%"} minSize={"15%"} className="h-full border-r border-[var(--sl-color-border)] bg-[var(--sl-color-bg)] overflow-y-auto">
                                        <TutorialFileTree
                                            files={files}
                                            activeFile={activeFile}
                                            onFileSelect={setActiveFile}
                                        />
                                    </Panel>
                                    <Separator className="pw-separator-h" />
                                    <Panel defaultSize={"80%"} minSize={"50%"} style={{ height: '100%' }}>
                                        <div className="h-full w-full relative overflow-hidden">
                                            <Editor
                                                content={code}
                                                language="pywire"
                                                onChange={setCode}
                                            />
                                        </div>
                                    </Panel>
                                </Group>
                            </Panel>

                            <Separator className="pw-separator-v" />

                            {/* Bottom: Browser Preview */}
                            <Panel defaultSize={"50%"} minSize={"25%"} style={{ height: '100%' }}>
                                <div className="h-full w-full">
                                    <BrowserPreview url="/" onMessage={handlePreviewMessage} theme={theme} />
                                </div>
                            </Panel>
                        </Group>
                    </Panel>
                </Group>
            </div>
        </div >
    );
};

function useDebounce<T>(value: T, delay: number): T {
    const [debouncedValue, setDebouncedValue] = useState(value);
    useEffect(() => {
        const handler = setTimeout(() => setDebouncedValue(value), delay);
        return () => clearTimeout(handler);
    }, [value, delay]);
    return debouncedValue;
}
