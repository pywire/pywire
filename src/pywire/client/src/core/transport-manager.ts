import { Transport, ServerMessage } from './transports';
import { WebTransportTransport } from './transports/webtransport';
import { WebSocketTransport } from './transports/websocket';
import { HTTPTransport } from './transports/http';

export interface TransportConfig {
    /** Enable WebTransport (requires HTTPS and HTTP/3 server) */
    enableWebTransport?: boolean;
    /** Enable WebSocket */
    enableWebSocket?: boolean;
    /** Enable HTTP polling fallback */
    enableHTTP?: boolean;
    /** Custom WebTransport URL */
    webTransportUrl?: string;
    /** Custom WebSocket URL */
    webSocketUrl?: string;
    /** Custom HTTP base URL */
    httpUrl?: string;
}

const DEFAULT_CONFIG: TransportConfig = {
    enableWebTransport: true,
    enableWebSocket: true,
    enableHTTP: true
};

/**
 * Manages transport selection with automatic fallback.
 * Tries transports in order: WebTransport → WebSocket → HTTP
 */
export class TransportManager {
    private transport: Transport | null = null;
    private config: TransportConfig;
    private messageHandlers: ((msg: ServerMessage) => void)[] = [];
    private statusHandlers: ((connected: boolean) => void)[] = [];

    constructor(config: Partial<TransportConfig> = {}) {
        this.config = { ...DEFAULT_CONFIG, ...config };
    }

    /**
     * Connect using the best available transport with fallback.
     */
    async connect(): Promise<void> {
        const transports = this.getTransportPriority();

        for (const TransportClass of transports) {
            try {
                console.log(`PyWire: Trying ${TransportClass.name}...`);
                this.transport = new TransportClass();

                // Forward message handlers
                for (const handler of this.messageHandlers) {
                    this.transport.onMessage(handler);
                }

                // Forward status changes
                this.transport.onStatusChange((connected) => {
                    this.notifyStatusHandlers(connected);
                });

                await this.transport.connect();
                console.log(`PyWire: Connected via ${this.transport.name}`);
                return;

            } catch (e) {
                console.warn(`PyWire: ${TransportClass.name} failed, trying next...`, e);
                this.transport = null;
            }
        }

        throw new Error('PyWire: All transports failed');
    }

    /**
     * Get transport classes in priority order based on config and browser support.
     */
    private getTransportPriority(): (new (...args: unknown[]) => Transport)[] {
        const transports: (new (...args: unknown[]) => Transport)[] = [];

        // WebTransport - only if supported and enabled
        if (this.config.enableWebTransport && WebTransportTransport.isSupported()) {
            // Also check if we're on HTTPS (required for WebTransport)
            if (window.location.protocol === 'https:') {
                transports.push(WebTransportTransport as unknown as new (...args: unknown[]) => Transport);
            }
        }

        // WebSocket
        if (this.config.enableWebSocket && typeof WebSocket !== 'undefined') {
            transports.push(WebSocketTransport as unknown as new (...args: unknown[]) => Transport);
        }

        // HTTP (always available as final fallback)
        if (this.config.enableHTTP) {
            transports.push(HTTPTransport as unknown as new (...args: unknown[]) => Transport);
        }

        return transports;
    }

    /**
     * Send a message through the active transport.
     */
    send(message: object): void {
        if (this.transport) {
            this.transport.send(message);
        } else {
            console.warn('PyWire: No active transport');
        }
    }

    /**
     * Register a message handler.
     */
    onMessage(handler: (msg: ServerMessage) => void): void {
        this.messageHandlers.push(handler);
        if (this.transport) {
            this.transport.onMessage(handler);
        }
    }

    /**
     * Register a connection status change handler.
     */
    onStatusChange(handler: (connected: boolean) => void): void {
        this.statusHandlers.push(handler);
    }

    private notifyStatusHandlers(connected: boolean): void {
        for (const handler of this.statusHandlers) {
            handler(connected);
        }
    }

    /**
     * Disconnect the active transport.
     */
    disconnect(): void {
        if (this.transport) {
            this.transport.disconnect();
            this.transport = null;
            this.notifyStatusHandlers(false);
        }
    }

    /**
     * Get the name of the active transport.
     */
    getActiveTransport(): string | null {
        return this.transport?.name || null;
    }

    /**
     * Check if connected.
     */
    isConnected(): boolean {
        return this.transport?.isConnected() || false;
    }
}
