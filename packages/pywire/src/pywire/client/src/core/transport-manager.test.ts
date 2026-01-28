import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TransportManager } from './transport-manager';
import { WebTransportTransport } from './transports/webtransport';
import { WebSocketTransport } from './transports/websocket';
import { HTTPTransport } from './transports/http';

// Create mock classes that can be used in the tests
class MockWebTransport {
    static isSupported = vi.fn(() => true);
    connect = vi.fn().mockResolvedValue(undefined);
    onMessage = vi.fn();
    onStatusChange = vi.fn();
    isConnected = vi.fn(() => false);
    send = vi.fn();
    disconnect = vi.fn();
    name = 'WebTransportTransport';
}

class MockWebSocket {
    connect = vi.fn().mockResolvedValue(undefined);
    onMessage = vi.fn();
    onStatusChange = vi.fn();
    isConnected = vi.fn(() => false);
    send = vi.fn();
    disconnect = vi.fn();
    name = 'WebSocketTransport';
}

class MockHTTP {
    connect = vi.fn().mockResolvedValue(undefined);
    onMessage = vi.fn();
    onStatusChange = vi.fn();
    isConnected = vi.fn(() => false);
    send = vi.fn();
    disconnect = vi.fn();
    name = 'HTTPTransport';
}

vi.mock('./transports/webtransport', () => ({
    WebTransportTransport: vi.fn()
}));

vi.mock('./transports/websocket', () => ({
    WebSocketTransport: vi.fn()
}));

vi.mock('./transports/http', () => ({
    HTTPTransport: vi.fn()
}));

// Set static properties on the mocked constructors
(WebTransportTransport as any).isSupported = MockWebTransport.isSupported;
Object.defineProperty(WebTransportTransport, 'name', { value: 'WebTransportTransport' });
Object.defineProperty(WebSocketTransport, 'name', { value: 'WebSocketTransport' });
Object.defineProperty(HTTPTransport, 'name', { value: 'HTTPTransport' });

describe('TransportManager', () => {
    beforeEach(() => {
        vi.clearAllMocks();

        // Default mock implementations (successful connect)
        (WebTransportTransport as any).mockImplementation(MockWebTransport);
        (WebSocketTransport as any).mockImplementation(MockWebSocket);
        (HTTPTransport as any).mockImplementation(MockHTTP);

        vi.stubGlobal('location', { protocol: 'https:' });
        vi.stubGlobal('WebSocket', vi.fn());
        (WebTransportTransport as any).isSupported.mockReturnValue(true);
    });

    it('should try WebTransport first if supported and on HTTPS', async () => {
        const manager = new TransportManager();
        await manager.connect();

        expect(WebTransportTransport).toHaveBeenCalled();
        expect(manager.getActiveTransport()).toBe('WebTransportTransport');
    });

    it('should fallback to WebSocket if WebTransport fails', async () => {
        (WebTransportTransport as any).mockImplementation(class extends MockWebTransport {
            connect = vi.fn().mockRejectedValue(new Error('WT failed'));
        });

        const manager = new TransportManager();
        await manager.connect();

        expect(WebTransportTransport).toHaveBeenCalled();
        expect(WebSocketTransport).toHaveBeenCalled();
        expect(manager.getActiveTransport()).toBe('WebSocketTransport');
    });

    it('should fallback to HTTP if WebSocket fails', async () => {
        (WebTransportTransport as any).mockImplementation(class extends MockWebTransport {
            connect = vi.fn().mockRejectedValue(new Error('WT failed'));
        });
        (WebSocketTransport as any).mockImplementation(class extends MockWebSocket {
            connect = vi.fn().mockRejectedValue(new Error('WS failed'));
        });

        const manager = new TransportManager();
        await manager.connect();

        expect(HTTPTransport).toHaveBeenCalled();
        expect(manager.getActiveTransport()).toBe('HTTPTransport');
    });

    it('should skip WebTransport if not on HTTPS', async () => {
        vi.stubGlobal('location', { protocol: 'http:' });
        const manager = new TransportManager();
        await manager.connect();

        expect(WebTransportTransport).not.toHaveBeenCalled();
        expect(WebSocketTransport).toHaveBeenCalled();
    });

    it('should respect config to disable transports', async () => {
        const manager = new TransportManager({ enableWebTransport: false });
        await manager.connect();

        expect(WebTransportTransport).not.toHaveBeenCalled();
        expect(WebSocketTransport).toHaveBeenCalled();
    });

    it('should throw if all transports fail', async () => {
        (WebTransportTransport as any).mockImplementation(class extends MockWebTransport {
            connect = vi.fn().mockRejectedValue(new Error('WT failed'));
        });
        (WebSocketTransport as any).mockImplementation(class extends MockWebSocket {
            connect = vi.fn().mockRejectedValue(new Error('WS failed'));
        });
        (HTTPTransport as any).mockImplementation(class extends MockHTTP {
            connect = vi.fn().mockRejectedValue(new Error('HTTP failed'));
        });

        const manager = new TransportManager();
        await expect(manager.connect()).rejects.toThrow('PyWire: All transports failed');
    });

    it('should forward messages to registered handlers', async () => {
        const onMessageSpy = vi.fn();
        (WebTransportTransport as any).mockImplementation(class extends MockWebTransport {
            onMessage = onMessageSpy;
        });

        const manager = new TransportManager();
        const handler = vi.fn();
        manager.onMessage(handler);

        await manager.connect();

        expect(onMessageSpy).toHaveBeenCalledWith(handler);
    });
});
