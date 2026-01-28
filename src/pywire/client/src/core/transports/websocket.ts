import { BaseTransport, ServerMessage } from './base';
import { encode, decode } from '@msgpack/msgpack';

/**
 * WebSocket transport implementation.
 */
export class WebSocketTransport extends BaseTransport {
    readonly name = 'WebSocket';

    private socket: WebSocket | null = null;
    private reconnectAttempts = 0;
    private maxReconnectDelay = 5000;
    private shouldReconnect = true;
    private readonly url: string;

    constructor(url?: string) {
        super();
        this.url = url || this.getDefaultUrl();
    }

    private getDefaultUrl(): string {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${protocol}//${window.location.host}/_pywire/ws`;
    }

    connect(): Promise<void> {
        return new Promise((resolve, reject) => {
            try {
                this.socket = new WebSocket(this.url);
                this.socket.binaryType = 'arraybuffer';

                this.socket.onopen = () => {
                    console.log('PyWire: WebSocket connected');
                    this.notifyStatus(true);
                    this.reconnectAttempts = 0;
                    resolve();
                };

                this.socket.onmessage = (event: MessageEvent) => {
                    try {
                        const msg = decode(event.data) as ServerMessage;
                        this.notifyHandlers(msg);
                    } catch (e) {
                        console.error('PyWire: Error parsing WebSocket message', e);
                    }
                };

                this.socket.onclose = () => {
                    console.log('PyWire: WebSocket disconnected');
                    this.notifyStatus(false);
                    if (this.shouldReconnect) {
                        this.scheduleReconnect();
                    }
                };

                this.socket.onerror = (error) => {
                    console.error('PyWire: WebSocket error', error);
                    if (!this.connected) {
                        reject(new Error('WebSocket connection failed'));
                    }
                };
            } catch (e) {
                reject(e);
            }
        });
    }

    send(message: object): void {
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(encode(message));
        } else {
            console.warn('PyWire: Cannot send message, WebSocket not open');
        }
    }

    disconnect(): void {
        this.shouldReconnect = false;
        if (this.socket) {
            this.socket.close();
            this.socket = null;
        }
        this.notifyStatus(false);
    }

    private scheduleReconnect(): void {
        const delay = Math.min(
            1000 * Math.pow(2, this.reconnectAttempts),
            this.maxReconnectDelay
        );

        console.log(`PyWire: Reconnecting in ${delay}ms...`);

        setTimeout(() => {
            this.reconnectAttempts++;
            this.connect().catch(() => {
                // Reconnect will be scheduled again on close
            });
        }, delay);
    }
}
