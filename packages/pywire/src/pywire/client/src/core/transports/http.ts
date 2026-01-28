import { BaseTransport, ServerMessage } from './base';
import { encode, decode } from '@msgpack/msgpack';

/**
 * HTTP polling transport as a fallback when WebTransport and WebSocket are unavailable.
 * Uses long-polling for receiving updates and POST for sending events.
 */
export class HTTPTransport extends BaseTransport {
    readonly name = 'HTTP';

    private polling = false;
    private pollAbortController: AbortController | null = null;
    private readonly baseUrl: string;
    private sessionId: string | null = null;

    constructor(baseUrl?: string) {
        super();
        this.baseUrl = baseUrl || `${window.location.origin}/_pywire`;
    }

    async connect(): Promise<void> {
        try {
            // Initialize session with the server
            const response = await fetch(`${this.baseUrl}/session`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-msgpack',
                    'Accept': 'application/x-msgpack'
                },
                body: encode({ path: window.location.pathname + window.location.search })
            });

            if (!response.ok) {
                throw new Error(`HTTP session init failed: ${response.status}`);
            }

            const buffer = await response.arrayBuffer();
            const data = decode(buffer) as { sessionId: string };
            this.sessionId = data.sessionId;

            console.log('PyWire: HTTP transport connected');
            this.notifyStatus(true);

            // Start polling for updates
            this.startPolling();

        } catch (e) {
            console.error('PyWire: HTTP transport connection failed', e);
            throw e;
        }
    }

    private async startPolling(): Promise<void> {
        if (this.polling) return;
        this.polling = true;

        while (this.polling && this.connected) {
            try {
                this.pollAbortController = new AbortController();

                const response = await fetch(`${this.baseUrl}/poll?session=${this.sessionId}`, {
                    method: 'GET',
                    signal: this.pollAbortController.signal,
                    headers: {
                        'Accept': 'application/x-msgpack'
                    }
                });

                if (!response.ok) {
                    if (response.status === 404) {
                        // Session expired, try to reconnect
                        console.warn('PyWire: HTTP session expired, reconnecting...');
                        this.notifyStatus(false);
                        await this.connect();
                        return;
                    }
                    throw new Error(`Poll failed: ${response.status}`);
                }

                const buffer = await response.arrayBuffer();
                const messages = decode(buffer) as ServerMessage[];

                for (const msg of messages) {
                    this.notifyHandlers(msg);
                }

            } catch (e) {
                if (e instanceof Error && e.name === 'AbortError') {
                    // Polling was aborted intentionally
                    break;
                }
                console.error('PyWire: HTTP poll error', e);
                // Wait a bit before retrying
                await this.sleep(1000);
            }
        }
    }

    async send(message: object): Promise<void> {
        if (!this.connected || !this.sessionId) {
            console.warn('PyWire: Cannot send message, HTTP transport not connected');
            return;
        }

        try {
            const response = await fetch(`${this.baseUrl}/event`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-msgpack',
                    'Accept': 'application/x-msgpack',
                    'X-PyWire-Session': this.sessionId
                },
                body: encode(message)
            });

            if (!response.ok) {
                throw new Error(`Event send failed: ${response.status}`);
            }

            // The response contains the updated HTML
            const buffer = await response.arrayBuffer();
            const result = decode(buffer) as ServerMessage;
            this.notifyHandlers(result);

        } catch (e) {
            console.error('PyWire: HTTP send error', e);
        }
    }

    disconnect(): void {
        this.polling = false;
        this.notifyStatus(false);

        if (this.pollAbortController) {
            this.pollAbortController.abort();
            this.pollAbortController = null;
        }

        this.sessionId = null;
    }

    private sleep(ms: number): Promise<void> {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}
