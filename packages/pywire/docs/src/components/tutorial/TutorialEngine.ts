export type TutorialStep = {
    id: string;
    title: string;
    description: string;
    initialCode: string;
    targetCode?: string;
    validation?: (code: string) => boolean;
};

// Global singleton key
const GLOBAL_ENGINE_KEY = '__PYWIRE_TUTORIAL_ENGINE__';

// Type declaration for window
declare global {
    interface Window {
        [GLOBAL_ENGINE_KEY]?: TutorialEngine;
    }
}

export class TutorialEngine {
    private worker: Worker;
    private onReady: () => void;
    private onResponse: (data: any) => void;
    private onLog: (msg: string) => void;
    private _isReady: boolean = false;

    constructor(options: {
        onReady: () => void;
        onResponse: (data: any) => void;
        onLog: (msg: string) => void;
    }) {
        this.onReady = options.onReady;
        this.onResponse = options.onResponse;
        this.onLog = options.onLog;

        const pathBase = import.meta.env.BASE_URL === '/' ? '/' : import.meta.env.BASE_URL + '/';
        // Ensure baseUrl is absolute (http/https) so micropip works
        const origin = window.location.origin;
        const baseUrl = `${origin}${pathBase}`;

        this.worker = new Worker(`${pathBase}pywire-worker.js`);
        this.worker.onmessage = this.handleWorkerMessage.bind(this);

        this.worker.postMessage({ type: 'INIT', payload: { baseUrl } });
    }

    /**
     * Get or create the global TutorialEngine singleton.
     * This persists across React component remounts during navigation.
     */
    public static getInstance(options: {
        onReady: () => void;
        onResponse: (data: any) => void;
        onLog: (msg: string) => void;
    }): TutorialEngine {
        if (typeof window !== 'undefined' && window[GLOBAL_ENGINE_KEY]) {
            console.log('[TutorialEngine] Reusing existing global engine instance');
            const engine = window[GLOBAL_ENGINE_KEY]!;
            // Update callbacks for the new component instance
            engine.updateCallbacks(options);
            return engine;
        }

        console.log('[TutorialEngine] Creating new global engine instance');
        const engine = new TutorialEngine(options);
        if (typeof window !== 'undefined') {
            window[GLOBAL_ENGINE_KEY] = engine;
        }
        return engine;
    }

    /**
     * Update the callbacks. Called when the component remounts.
     */
    public updateCallbacks(options: {
        onReady: () => void;
        onResponse: (data: any) => void;
        onLog: (msg: string) => void;
    }) {
        this.onReady = options.onReady;
        this.onResponse = options.onResponse;
        this.onLog = options.onLog;

        // If already ready, immediately call the new onReady callback
        if (this._isReady) {
            console.log('[TutorialEngine] Already ready, calling new onReady callback');
            this.onReady();
        }
    }

    /**
     * Check if the engine is already initialized and ready.
     */
    public get isReady(): boolean {
        return this._isReady;
    }

    private handleWorkerMessage(event: MessageEvent) {
        const { type, message, id } = event.data;

        if (type === 'READY') {
            this._isReady = true;
            this.onReady();
        } else if (type === 'http_response' || type === 'ws_message') {
            this.onResponse(event.data);
        } else if (type === 'STDOUT' || type === 'STDERR') {
            this.onLog(message);
        }
    }

    private sanitizePayload(obj: any): any {
        if (obj === null || typeof obj !== 'object') {
            return obj;
        }

        if (Array.isArray(obj)) {
            return obj.map(item => this.sanitizePayload(item));
        }

        const sanitized: any = {};
        for (const [key, value] of Object.entries(obj)) {
            if (value !== undefined) {
                sanitized[key] = this.sanitizePayload(value);
            }
        }
        return sanitized;
    }

    private postToWorker(message: any) {
        this.worker.postMessage(this.sanitizePayload(message));
    }

    public restart(pagesDir?: string) {
        this.postToWorker({
            type: 'RESTART',
            payload: { pagesDir },
        });
    }

    public updateFile(filename: string, content: string) {
        this.postToWorker({
            type: 'UPDATE_FILE',
            payload: { filename, content },
        });
    }

    public reset() {
        this.postToWorker({ type: 'RESET' });
    }

    public httpRequest(method: string, path: string, body?: any) {
        this.postToWorker({
            type: 'REQUEST',
            payload: {
                type: 'http_request',
                id: Math.random().toString(36).substr(2, 9),
                method,
                path,
                headers: { 'Accept': 'text/html' },
                body,
            },
        });
    }

    public wsConnect(path: string) {
        this.postToWorker({
            type: 'REQUEST',
            payload: {
                type: 'ws_connect',
                id: 'ws-main',
                path,
            },
        });
    }

    public wsSend(data: ArrayLike<number> | string) {
        // Convert ArrayBuffer/Uint8Array to regular array for postMessage serialization
        const serializedData = typeof data === 'string'
            ? data
            : Array.from(data as ArrayLike<number>);

        this.postToWorker({
            type: 'REQUEST',
            payload: {
                type: 'ws_send',
                id: 'ws-main',
                data: serializedData,
            },
        });
    }
}

