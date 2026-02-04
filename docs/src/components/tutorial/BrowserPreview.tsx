import React from 'react';
import { Preview } from './Preview';
import { RefreshCw, Globe, ChevronLeft, ChevronRight } from 'lucide-react';

interface BrowserPreviewProps {
    url: string;
    onMessage: (msg: any) => void;
    theme?: 'light' | 'dark';
}

export const BrowserPreview: React.FC<BrowserPreviewProps> = ({ url, onMessage, theme = 'dark' }) => {
    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            height: '100%',
            width: '100%',
            backgroundColor: '#0f1117',
            overflow: 'hidden'
        }}>
            {/* URL Bar Area */}
            <div className="pw-browser-url-bar">
                <div className="pw-browser-controls">
                    <div className="pw-browser-dot" style={{ backgroundColor: '#ff5f56' }}></div>
                    <div className="pw-browser-dot" style={{ backgroundColor: '#ffbd2e' }}></div>
                    <div className="pw-browser-dot" style={{ backgroundColor: '#27c93f' }}></div>
                </div>

                <div className="pw-browser-nav">
                    <button
                        type="button"
                        onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            e.nativeEvent.stopImmediatePropagation();
                            (window as any).__PYWIRE_PREVIEW_BACK__?.();
                        }}
                        title="Back"
                        className="pw-btn-icon"
                    >
                        <ChevronLeft size={16} />
                    </button>
                    <button
                        type="button"
                        onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            e.nativeEvent.stopImmediatePropagation();
                            (window as any).__PYWIRE_PREVIEW_FORWARD__?.();
                        }}
                        title="Forward"
                        className="pw-btn-icon"
                    >
                        <ChevronRight size={16} />
                    </button>
                    <button
                        type="button"
                        onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            e.nativeEvent.stopImmediatePropagation();
                            (window as any).__PYWIRE_PREVIEW_RELOAD__?.();
                        }}
                        title="Reload"
                        className="pw-btn-icon"
                    >
                        <RefreshCw size={14} />
                    </button>
                </div>

                <div className="pw-browser-url-display">
                    <Globe size={12} style={{ color: '#9ca3af', flexShrink: 0 }} />
                    <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {url.startsWith('/') ? url : `/${url}`}
                    </span>
                </div>
            </div>

            {/* Preview Content */}
            <div style={{ flex: 1, position: 'relative' }}>
                <Preview url={url} onMessage={onMessage} theme={theme} />
            </div>
        </div>
    );
};
