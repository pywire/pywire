import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Panel, Group, Separator } from 'react-resizable-panels';
import { Editor } from './Editor';
import { BrowserPreview } from './BrowserPreview';
import { TutorialFileTree } from './tree/TutorialFileTree';
import { LoadingSpinner } from './LoadingSpinner';
import { TutorialEngine } from './TutorialEngine';
import { useTutorialStorage } from '../../hooks/useTutorialStorage';
import { ChevronLeft, ChevronRight, Menu, Wrench, ArrowLeft, ArrowRight } from 'lucide-react';
import type { TutorialStep } from './types';
import { MarkdownRenderer } from './MarkdownRenderer';

import '../../styles/pywire-tutorial.css';

interface TutorialWorkspaceProps {
    initialSlug: string;
    allSteps: TutorialStep[];
}

export const TutorialWorkspace: React.FC<TutorialWorkspaceProps> = ({
    initialSlug,
    allSteps
}) => {
    // SPA Routing State
    const [currentSlug, setCurrentSlug] = useState(initialSlug);

    // Derived State
    const currentIndex = allSteps.findIndex(s => s.slug === currentSlug);
    const currentStep = allSteps[currentIndex !== -1 ? currentIndex : 0];
    const nextStep = currentIndex < allSteps.length - 1 ? allSteps[currentIndex + 1] : undefined;
    const prevStep = currentIndex > 0 ? allSteps[currentIndex - 1] : undefined;

    // Safety check if slug is invalid
    if (currentIndex === -1 && allSteps.length > 0) {
        console.warn(`Invalid slug ${currentSlug}, falling back to first step`);
    }

    // Persistence: engineRef stays alive across props changes because the component stays mounted
    const engineRef = useRef<TutorialEngine | null>(null);
    const [isReady, setIsReady] = useState(false);
    const [loadingMessage, setLoadingMessage] = useState('Initializing Pyodide...');
    const [theme, setTheme] = useState<'light' | 'dark'>('dark');

    // Code state - using step-specific storage
    const [code, setCode] = useTutorialStorage(currentStep.slug, currentStep.initialCode);
    const [activeFile, setActiveFile] = useState(currentStep.files[0] || 'index.wire');
    const debouncedCode = useDebounce(code, 600);

    // Handle History (Browser Back/Forward)
    useEffect(() => {
        const handlePopState = (event: PopStateEvent) => {
            // If state has step, use it. Otherwise try to parse URL.
            // But simpler: just parse URL always.
            const path = window.location.pathname;
            const match = path.match(/\/docs\/tutorial\/([^/]+)/);
            if (match && match[1]) {
                setCurrentSlug(match[1]);
            }
        };

        window.addEventListener('popstate', handlePopState);
        return () => window.removeEventListener('popstate', handlePopState);
    }, []);

    // Navigation function
    const navigateTo = (slug: string) => {
        setCurrentSlug(slug);
        const newUrl = `/docs/tutorial/${slug}`;
        window.history.pushState({ slug }, '', newUrl);
    };

    // Re-initialize code when step changes (if not already in storage)
    useEffect(() => {
        setActiveFile(currentStep.files[0] || 'index.wire');
        if (isReady && engineRef.current) {
            engineRef.current.reset();
        }
    }, [currentStep.slug, isReady]);

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
                            <button
                                onClick={() => navigateTo(prevStep.slug)}
                                className="pw-btn-icon-sm"
                                title={`Previous: ${prevStep.title}`}
                            >
                                <ArrowLeft size={18} />
                            </button>
                        ) : (
                            <div className="pw-btn-icon-sm disabled">
                                <ArrowLeft size={18} />
                            </div>
                        )}
                        {nextStep ? (
                            <button
                                onClick={() => navigateTo(nextStep.slug)}
                                className="pw-btn-icon-sm"
                                title={`Next: ${nextStep.title}`}
                            >
                                <ArrowRight size={18} />
                            </button>
                        ) : (
                            <div className="pw-btn-icon-sm disabled">
                                <ArrowRight size={18} />
                            </div>
                        )}
                    </div>

                    <div className="pw-breadcrumb ml-4">
                        <span className="pw-breadcrumb-prefix">PyWire Tutorial</span>
                        <span className="pw-breadcrumb-separator">/</span>
                        <span className="pw-breadcrumb-title">{currentStep.title}</span>
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
                    <Panel defaultSize={30} minSize={20} className="h-full border-r border-[var(--sl-color-border)] bg-[var(--sl-color-bg)]">
                        <div className="h-full overflow-y-auto pw-instructions-container">
                            <MarkdownRenderer content={currentStep.content} />
                        </div>
                    </Panel>

                    <Separator className="pw-separator-h" />

                    {/* Right: Work Area (Split Top/Bottom) */}
                    <Panel defaultSize={70} minSize={40} className="h-full">
                        <Group orientation="vertical" className="h-full">
                            {/* Top: Files + Editor */}
                            <Panel defaultSize={50} minSize={25} className="h-full flex flex-col">
                                <Group orientation="horizontal" className="flex-1 min-h-0">
                                    <Panel defaultSize={20} minSize={15} className="h-full border-r border-[var(--sl-color-border)] bg-[var(--sl-color-bg)] overflow-y-auto">
                                        <TutorialFileTree
                                            files={currentStep.files}
                                            activeFile={activeFile}
                                            onFileSelect={setActiveFile}
                                        />
                                    </Panel>
                                    <Separator className="pw-separator-h" />
                                    <Panel defaultSize={80} minSize={50} style={{ height: '100%' }}>
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
                            <Panel defaultSize={50} minSize={25} style={{ height: '100%' }}>
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

