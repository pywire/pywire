import { BaseTransport, ServerMessage } from './base';

/**
 * WebTransport implementation using the browser's native WebTransport API.
 * WebTransport provides lower latency than WebSocket via HTTP/3 and QUIC.
 */
export class WebTransportTransport extends BaseTransport {
    readonly name = 'WebTransport';

    private transport: WebTransport | null = null;
    private writer: WritableStreamDefaultWriter<Uint8Array> | null = null;
    private readonly url: string;
    private encoder = new TextEncoder();
    private decoder = new TextDecoder();

    constructor(url?: string) {
        super();
        this.url = url || this.getDefaultUrl();
    }

    private getDefaultUrl(): string {
        // WebTransport requires HTTPS
        return `https://${window.location.host}/_pywire/webtransport`;
    }

    /**
     * Check if WebTransport is available in this browser.
     */
    static isSupported(): boolean {
        return typeof WebTransport !== 'undefined';
    }

    async connect(): Promise<void> {
        if (!WebTransportTransport.isSupported()) {
            throw new Error('WebTransport not supported in this browser');
        }

        try {
            // Check for self-signed cert hash (Dev Mode)
            const options: any = {};
            const certHash = (window as any).PYWIRE_CERT_HASH;
            if (certHash && Array.isArray(certHash)) {
                options.serverCertificateHashes = [{
                    algorithm: 'sha-256',
                    value: new Uint8Array(certHash)
                }];
                console.log("PyWire: Using explicit certificate hash for WebTransport");
            }

            this.transport = new WebTransport(this.url, options);

            // Wait for the connection to be ready
            await this.transport.ready;

            console.log('PyWire: WebTransport ready');
            this.connected = true;

            // Start reading incoming streams
            this.startReading();

        } catch (e) {
            this.handleDisconnect();
            throw e;
        }
    }

    private async startReading(): Promise<void> {
        if (!this.transport) return;

        // Read from bidirectional streams
        const reader = this.transport.incomingBidirectionalStreams.getReader();

        try {
            while (true) {
                const { value: stream, done } = await reader.read();
                if (done) break;

                // Handle each incoming stream
                this.handleStream(stream);
            }
        } catch (e) {
            if (this.connected) {
                console.error('PyWire: WebTransport read error', e);
                this.handleDisconnect();
            }
        }
    }

    private async handleStream(stream: WebTransportBidirectionalStream): Promise<void> {
        const reader = stream.readable.getReader();

        try {
            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                if (value) {
                    const text = this.decoder.decode(value);
                    try {
                        const msg = JSON.parse(text) as ServerMessage;
                        this.notifyHandlers(msg);
                    } catch (e) {
                        console.error('PyWire: Error parsing WebTransport message', e);
                    }
                }
            }
        } catch (e) {
            console.error('PyWire: Stream read error', e);
        }
    }

    async send(message: object): Promise<void> {
        if (!this.transport || !this.connected) {
            console.warn('PyWire: Cannot send message, WebTransport not connected');
            return;
        }

        try {
            // Create a new bidirectional stream for each message
            const stream = await this.transport.createBidirectionalStream();
            const writer = stream.writable.getWriter();

            const data = this.encoder.encode(JSON.stringify(message));
            await writer.write(data);
            await writer.close();

            // Read the response from this stream
            this.handleStream(stream);

        } catch (e) {
            console.error('PyWire: WebTransport send error', e);
        }
    }

    disconnect(): void {
        if (this.transport) {
            this.transport.close();
            this.transport = null;
        }
        this.writer = null;
        this.connected = false;
    }

    private handleDisconnect(): void {
        this.connected = false;
        this.transport = null;
        this.writer = null;
    }
}
