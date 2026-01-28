import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ErrorTraceHandler } from './error-trace';

describe('ErrorTraceHandler', () => {
    let handler: ErrorTraceHandler;

    beforeEach(() => {
        vi.clearAllMocks();
        handler = new ErrorTraceHandler();
        vi.stubGlobal('location', { origin: 'http://localhost:8000' });
        vi.stubGlobal('fetch', vi.fn());
        vi.stubGlobal('console', { error: vi.fn(), warn: vi.fn(), log: vi.fn() });
        // vi.stubGlobal('eval', vi.fn()); // indirect eval is hard to mock, but we can check if it's called
    });

    it('should generate virtual URLs correctly', () => {
        // getVirtualUrl is private, so we'll test it through handle()'s side effects or by casting
        const virtualUrl = (handler as any).getVirtualUrl('/path/to/script.py');
        expect(virtualUrl).toContain('http://localhost:8000/_pywire/file/');
        expect(virtualUrl).toContain('script.py');
    });

    it('should fetch source files and inject them with sourceURL', async () => {
        const fetchMock = vi.mocked(fetch);
        fetchMock.mockResolvedValue({
            ok: true,
            text: async () => 'print("hello")'
        } as Response);

        const trace = [
            { filename: '/path/to/script.py', lineno: 10, colno: 5, name: 'my_func', line: 'def my_func():' }
        ];

        await handler.handle('Test Error', trace);

        expect(fetchMock).toHaveBeenCalledWith('/_pywire/source?path=%2Fpath%2Fto%2Fscript.py');
        // We expect console.error to have been called with the constructed stack
        expect(vi.mocked(console.error)).toHaveBeenCalledWith(
            expect.stringContaining('at my_func (http://localhost:8000/_pywire/file/')
        );
        expect(vi.mocked(console.error)).toHaveBeenCalledWith(
            expect.stringContaining(':10:5)')
        );
    });

    it('should handle missing column numbers', async () => {
        vi.mocked(fetch).mockResolvedValue({ ok: false } as Response);

        const trace = [
            { filename: 'test.py', lineno: 5, name: 'foo', line: 'x = 1' }
        ];

        await handler.handle('Error', trace);

        expect(vi.mocked(console.error)).toHaveBeenCalledWith(
            expect.stringContaining('at foo (http://localhost:8000/_pywire/file/')
        );
        expect(vi.mocked(console.error)).toHaveBeenCalledWith(
            expect.stringContaining(':5:1)') // Default colno is 1
        );
    });

    it('should not reload already loaded sources', async () => {
        const fetchMock = vi.mocked(fetch);
        fetchMock.mockResolvedValue({
            ok: true,
            text: async () => 'content'
        } as Response);

        const trace = [{ filename: 'test.py', lineno: 1, name: 'foo', line: 'content' }];

        await handler.handle('Err 1', trace);
        await handler.handle('Err 2', trace);

        expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it('should handle fetch failures gracefully', async () => {
        vi.mocked(fetch).mockRejectedValue(new Error('Network error'));

        const trace = [{ filename: 'test.py', lineno: 1, name: 'foo', line: 'content' }];

        await handler.handle('Err', trace);

        expect(vi.mocked(console.warn)).toHaveBeenCalledWith(
            expect.stringContaining('PyWire: Failed to load source'),
            'test.py',
            expect.any(Error)
        );
        // Should still log the error stack
        expect(vi.mocked(console.error)).toHaveBeenCalled();
    });
});
