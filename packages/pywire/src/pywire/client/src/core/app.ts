import { TransportManager, TransportConfig } from './transport-manager';
import { DOMUpdater } from './dom-updater';
import { ServerMessage, ClientMessage, EventData, RelocateMessage } from './transports';
import { UnifiedEventHandler } from '../events/handler';

export interface PyWireConfig extends TransportConfig {
    /** Auto-initialize on DOMContentLoaded */
    autoInit?: boolean;
    /** Enable verbose debug logging */
    debug?: boolean;
}

const DEFAULT_CONFIG: PyWireConfig = {
    autoInit: true,
    enableWebTransport: true,
    enableWebSocket: true,
    enableHTTP: true,
    debug: false
};

/**
 * Core PyWire Application class.
 * Provides transport, DOM updates, SPA navigation, and event handling.
 * Dev-only features (status overlay, error traces) are in the dev bundle.
 */
export class PyWireApp {
    protected transport: TransportManager;
    protected updater: DOMUpdater;
    protected eventHandler: UnifiedEventHandler;
    protected initialized = false;
    protected config: PyWireConfig;
    protected siblingPaths: string[] = [];
    protected pathRegexes: RegExp[] = [];
    protected pjaxEnabled = false;
    protected isConnected = false;

    constructor(config: Partial<PyWireConfig> = {}) {
        this.config = { ...DEFAULT_CONFIG, ...config };
        this.transport = new TransportManager(this.config);
        this.updater = new DOMUpdater(this.config.debug);
        this.eventHandler = new UnifiedEventHandler(this);
    }

    getConfig(): PyWireConfig {
        return this.config;
    }

    /**
     * Initialize the PyWire application.
     */
    async init(): Promise<void> {
        if (this.initialized) return;
        this.initialized = true;

        // Setup message handling
        this.transport.onMessage((msg) => this.handleMessage(msg));
        this.transport.onStatusChange((connected) => this.handleStatusChange(connected));

        // Connect transport with fallback
        try {
            await this.transport.connect();
        } catch (e) {
            console.error('PyWire: Failed to connect:', e);
        }

        // Load SPA metadata and setup navigation
        this.loadSPAMetadata();
        this.setupSPANavigation();

        // Setup event interception via UnifiedEventHandler
        this.eventHandler.init();

        console.log(`PyWire: Initialized (transport: ${this.transport.getActiveTransport()}, spa_paths: ${this.siblingPaths.length}, pjax: ${this.pjaxEnabled})`);
    }

    /**
     * Handle connection status changes. Override in dev bundle for UI.
     */
    protected handleStatusChange(connected: boolean): void {
        this.isConnected = connected;
        // Base implementation: no UI, just track state
    }

    /**
     * Load SPA navigation metadata from injected script tag.
     */
    protected loadSPAMetadata(): void {
        const metaScript = document.getElementById('_pywire_spa_meta');
        if (metaScript) {
            try {
                const meta = JSON.parse(metaScript.textContent || '{}');
                this.siblingPaths = meta.sibling_paths || [];
                this.pjaxEnabled = !!meta.enable_pjax;
                if (meta.debug !== undefined) {
                    this.config.debug = !!meta.debug;
                }
                // Convert path patterns to regexes for matching
                this.pathRegexes = this.siblingPaths.map(p => this.patternToRegex(p));
            } catch (e) {
                console.warn('PyWire: Failed to parse SPA metadata', e);
            }
        }
    }

    /**
     * Convert route pattern like '/a/:id' to regex.
     */
    protected patternToRegex(pattern: string): RegExp {
        // Escape special regex chars except for our placeholders
        let regex = pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&');
        // Replace :param:type or :param with capture groups
        regex = regex.replace(/:(\\w+)(:\\w+)?/g, '([^/]+)');
        // Replace {param:type} or {param} with capture groups
        regex = regex.replace(/\\{(\\w+)(:\\w+)?\\}/g, '([^/]+)');
        return new RegExp(`^${regex}$`);
    }

    /**
     * Check if a path matches any sibling path pattern.
     */
    protected isSiblingPath(path: string): boolean {
        return this.pathRegexes.some(regex => regex.test(path));
    }

    /**
     * Setup SPA navigation for sibling paths.
     */
    protected setupSPANavigation(): void {
        // Handle browser back/forward
        window.addEventListener('popstate', () => {
            this.sendRelocate(window.location.pathname + window.location.search);
        });

        if (this.siblingPaths.length === 0 && !this.pjaxEnabled) return;

        // Intercept link clicks
        document.addEventListener('click', (e) => {
            const link = (e.target as Element).closest('a[href]') as HTMLAnchorElement | null;
            if (!link) return;

            // Only intercept same-origin links
            if (link.origin !== window.location.origin) return;

            // Ignore special links
            if (link.hasAttribute('download') || link.target === '_blank') return;

            // Check if matches criteria
            let shouldIntercept = false;

            if (this.pjaxEnabled) {
                shouldIntercept = true;
            } else if (this.isSiblingPath(link.pathname)) {
                shouldIntercept = true;
            }

            if (shouldIntercept) {
                e.preventDefault();
                this.navigateTo(link.pathname + link.search);
            }
        });
    }

    /**
     * Navigate to a path using SPA navigation.
     */
    navigateTo(path: string): void {
        if (!this.isConnected) {
            console.warn('PyWire: Navigation blocked - Offline');
            return;
        }

        history.pushState({}, '', path);
        this.sendRelocate(path);
    }

    /**
     * Send relocate message to server.
     */
    protected sendRelocate(path: string): void {
        const message: RelocateMessage = {
            type: 'relocate',
            path
        };
        this.transport.send(message);
    }

    /**
     * Send an event to the server.
     */
    sendEvent(handler: string, data: EventData): void {
        const message: ClientMessage = {
            type: 'event',
            handler,
            path: window.location.pathname + window.location.search,
            data
        };
        this.transport.send(message);
    }

    /**
     * Handle incoming server message. Override in dev bundle for error_trace.
     */
    protected async handleMessage(msg: ServerMessage): Promise<void> {
        switch (msg.type) {
            case 'update':
                if (msg.html) {
                    this.updater.update(msg.html);
                }
                break;

            case 'reload':
                console.log('PyWire: Reloading...');
                window.location.reload();
                break;

            case 'error':
                console.error('PyWire: Server error:', msg.error);
                break;

            case 'error_trace':
                // In core bundle, just log the error (no source loading)
                console.error('PyWire: Error:', msg.error);
                break;

            case 'console':
                if (msg.lines && msg.lines.length > 0) {
                    const prefix = 'PyWire Server:';
                    const joined = msg.lines.join('\n');
                    if (msg.level === 'error') {
                        console.error(prefix, joined);
                    } else if (msg.level === 'warn') {
                        console.warn(prefix, joined);
                    } else {
                        console.log(prefix, joined);
                    }
                }
                break;

            default:
                console.warn('PyWire: Unknown message type', msg);
        }
    }

    /**
     * Get the current transport name.
     */
    getTransport(): string | null {
        return this.transport.getActiveTransport();
    }

    /**
     * Disconnect from the server.
     */
    disconnect(): void {
        this.transport.disconnect();
    }
}
