import { describe, it, expect, vi, beforeEach } from 'vitest';
import { DOMUpdater } from './dom-updater';
import morphdom from 'morphdom';

vi.mock('morphdom', () => ({
    default: vi.fn((from, to, options) => {
        // Basic simulation of morphdom: just replace content if no options,
        // or call hooks if provided (we only care about onBeforeElUpdated)
        return;
    })
}));

describe('DOMUpdater', () => {
    let updater: DOMUpdater;

    beforeEach(() => {
        vi.clearAllMocks();
        updater = new DOMUpdater();
        document.documentElement.innerHTML = '<body><div id="app"></div></body>';
    });

    it('should call morphdom with custom options', () => {
        updater.update('<html><body><div id="app">New</div></body></html>');
        expect(morphdom).toHaveBeenCalledWith(
            expect.any(Node),
            expect.stringContaining('New'),
            expect.objectContaining({
                onBeforeElUpdated: expect.any(Function)
            })
        );
    });

    it('should preserve input value if focused and similar', () => {
        const morphdomMock = vi.mocked(morphdom);
        updater.update('<html><body><input id="test" value="server"></body></html>');

        // Get the onBeforeElUpdated hook
        const options = morphdomMock.mock.calls[0][2];
        const onBeforeElUpdated = options?.onBeforeElUpdated;

        if (!onBeforeElUpdated) throw new Error('Hook not found');

        const fromEl = document.createElement('input');
        fromEl.value = 'server-ahead';
        vi.spyOn(document, 'activeElement', 'get').mockReturnValue(fromEl);

        const toEl = document.createElement('input');
        toEl.setAttribute('value', 'server');

        const result = onBeforeElUpdated(fromEl, toEl);

        expect(result).toBe(true);
        expect(toEl.value).toBe('server-ahead');
    });

    it('should NOT preserve input value if completely different', () => {
        const morphdomMock = vi.mocked(morphdom);
        updater.update('<html><body><input id="test" value="server"></body></html>');

        const options = morphdomMock.mock.calls[0][2];
        const onBeforeElUpdated = options?.onBeforeElUpdated;

        if (!onBeforeElUpdated) throw new Error('Hook not found');

        const fromEl = document.createElement('input');
        fromEl.value = 'user-typed-something-else';
        vi.spyOn(document, 'activeElement', 'get').mockReturnValue(fromEl);

        const toEl = document.createElement('input');
        toEl.setAttribute('value', 'server-new');
        (toEl as any).value = 'server-new';

        onBeforeElUpdated(fromEl, toEl);

        // Should NOT have overwritten toEl.value with fromEl.value because they don't start with each other
        expect(toEl.value).toBe('server-new');
    });
});
