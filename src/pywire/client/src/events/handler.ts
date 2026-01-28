import { PyWireApp } from '../core/app';
import { DOMUpdater } from '../core/dom-updater';
import { EventData } from '../core/transports';

// Type alias for backward compatibility
type Application = PyWireApp;

export class UnifiedEventHandler {
    private app: Application;
    private debouncers = new Map<string, number>();
    private throttlers = new Map<string, number>();

    private supportedEvents = [
        'click', 'submit', 'input', 'change',
        'keydown', 'keyup', 'focus', 'blur',
        'mouseenter', 'mouseleave', 'scroll', 'contextmenu'
    ];

    // Events that should be suppressed during DOM updates to prevent loops
    private suppressDuringUpdate = ['focus', 'blur', 'mouseenter', 'mouseleave'];

    constructor(app: Application) {
        this.app = app;
    }

    private debugLog(...args: any[]): void {
        if (this.app.getConfig().debug) {
            console.log(...args);
        }
    }

    /**
     * Initialize global event listeners.
     * Uses event delegation on document body.
     */
    init(): void {
        this.supportedEvents.forEach(eventType => {
            const options = (eventType === 'mouseenter' || eventType === 'mouseleave' || eventType === 'focus' || eventType === 'blur' || eventType === 'scroll')
                ? { capture: true } // These don't bubble nicely or at all in some cases
                : undefined;

            document.addEventListener(eventType, (e) => this.handleEvent(e), options);
        });
    }

    /**
     * Helper to parse handlers from element (legacy or multiple/JSON).
     */
    private getHandlers(element: HTMLElement, eventType: string): Array<{ name: string, modifiers: string[], args?: any[] }> {
        const handlerAttr = `data-on-${eventType}`;
        const attrValue = element.getAttribute(handlerAttr);
        if (!attrValue) return [];

        if (attrValue.trim().startsWith('[')) {
            try {
                const handlers = JSON.parse(attrValue);
                if (Array.isArray(handlers)) {
                    return handlers.map((h: any) => ({
                        name: h.handler,
                        modifiers: h.modifiers || [],
                        args: h.args
                    }));
                }
            } catch (e) {
                console.error('Error parsing event handlers:', e);
            }
        } else {
            // Legacy single handler
            const modifiersAttr = element.getAttribute(`data-modifiers-${eventType}`);
            const modifiers = modifiersAttr ? modifiersAttr.split(' ').filter(m => m) : [];
            return [{ name: attrValue, modifiers, args: undefined }];
        }
        return [];
    }

    /**
     * Main event handler.
     */
    private async handleEvent(e: Event): Promise<void> {
        const eventType = e.type;

        // Skip focus/blur/mouseenter/mouseleave events during DOM updates to prevent loops
        if (DOMUpdater.isUpdating && this.suppressDuringUpdate.includes(eventType)) {
            this.debugLog('[Handler] SUPPRESSING event during update:', eventType, 'isUpdating=', DOMUpdater.isUpdating);
            return;
        }

        this.debugLog('[Handler] Processing event:', eventType, 'isUpdating=', DOMUpdater.isUpdating);

        // 1. Delegated handlers (standard path walk with bubbling)
        const path = e.composedPath ? e.composedPath() : [];
        let propagationStopped = false;

        for (const node of path) {
            if (propagationStopped) break;

            if (node instanceof HTMLElement) {
                const element = node;
                const handlers = this.getHandlers(element, eventType);

                if (handlers.length > 0) {
                    this.debugLog('[handleEvent] Found handlers on', element.tagName, handlers);

                    for (const h of handlers) {
                        // Skip if it's a .window or .outside handler - those are handled globally
                        if (!h.modifiers.includes('window') && !h.modifiers.includes('outside')) {
                            this.processEvent(element, eventType, h.name, h.modifiers, e, h.args);
                            if (e.cancelBubble) propagationStopped = true;
                        }
                    }
                }
            }
        }

        // 2. Global handlers (.window, .outside)
        this.handleGlobalEvent(e);
    }

    /**
     * Handle modifiers that listen outside the normal delegation path.
     */
    private handleGlobalEvent(e: Event): void {
        const eventType = e.type;
        const windowSelector = `[data-modifiers-${eventType}*="window"]`;
        const outsideSelector = `[data-modifiers-${eventType}*="outside"]`;

        const candidates = document.querySelectorAll(`${windowSelector}, ${outsideSelector}`);

        candidates.forEach(el => {
            if (!(el instanceof HTMLElement)) return;

            const handlers = this.getHandlers(el, eventType);
            for (const h of handlers) {
                // .window: trigger regardless of where the event happened
                if (h.modifiers.includes('window')) {
                    this.processEvent(el, eventType, h.name, h.modifiers, e, h.args);
                }

                // .outside: trigger if target is NOT inside this element
                if (h.modifiers.includes('outside')) {
                    const target = e.target as Node | null;
                    if (target && !el.contains(target)) {
                        this.processEvent(el, eventType, h.name, h.modifiers, e, h.args);
                    }
                }
            }
        });
    }

    /**
     * Process an event for a specific element after it has been matched.
     */
    private processEvent(element: HTMLElement, eventType: string, handlerName: string, modifiers: string[], e: Event, explicitArgs?: any[]): void {
        this.debugLog('[processEvent]', eventType, 'handler:', handlerName, 'modifiers:', modifiers);

        // --- 1. Logic Modifers ---

        // .prevent
        if (modifiers.includes('prevent') || eventType === 'submit') {
            this.debugLog('[processEvent] Calling preventDefault');
            e.preventDefault();
        }

        // .stop
        if (modifiers.includes('stop')) {
            e.stopPropagation();
        }

        // .self
        if (modifiers.includes('self')) {
            if (e.target !== element) return;
        }

        // --- 2. Filter Modifiers ---

        // System modifiers (Shift, Ctrl, Alt, Meta) - supported on Keyboard and Mouse events
        if (modifiers.includes('shift') && !(e as any).shiftKey) return;
        if (modifiers.includes('ctrl') && !(e as any).ctrlKey) return;
        if (modifiers.includes('alt') && !(e as any).altKey) return;
        if (modifiers.includes('meta') && !(e as any).metaKey) return;
        if (modifiers.includes('cmd') && !(e as any).metaKey) return;

        if (e instanceof KeyboardEvent) {
            // Known key modifiers
            const knownKeys = ['enter', 'escape', 'space', 'tab', 'up', 'down', 'left', 'right'];
            // System modifiers that should NOT be treated as key constraints
            const systemMods = ['shift', 'ctrl', 'alt', 'meta', 'cmd', 'window', 'outside', 'prevent', 'stop', 'self', 'debounce', 'throttle'];

            // Key modifiers are anything that's not a system mod and is either a known key or a single character
            const keyModifiers = modifiers.filter(m => {
                if (systemMods.includes(m)) return false;
                if (m.startsWith('debounce') || m.startsWith('throttle')) return false;
                if (m.endsWith('ms')) return false; // Duration like 500ms
                return knownKeys.includes(m) || m.length === 1;
            });

            if (keyModifiers.length > 0) {
                const pressedKey = e.key.toLowerCase();
                this.debugLog('[processEvent] Key check. Pressed:', pressedKey, 'Modifiers:', keyModifiers);

                // Map for special keys
                const keyMap: Record<string, string> = {
                    'escape': 'escape',
                    'esc': 'escape',
                    'enter': 'enter',
                    'space': ' ',
                    'spacebar': ' ',
                    ' ': ' ',
                    'tab': 'tab',
                    'up': 'arrowup',
                    'arrowup': 'arrowup',
                    'down': 'arrowdown',
                    'arrowdown': 'arrowdown',
                    'left': 'arrowleft',
                    'arrowleft': 'arrowleft',
                    'right': 'arrowright',
                    'arrowright': 'arrowright'
                };

                // Normalize the pressed key
                const normalizedPressedKey = keyMap[pressedKey] || pressedKey;

                // Check if any key constraint matches
                let match = false;
                for (const constraint of keyModifiers) {
                    const targetKey = keyMap[constraint] || constraint;
                    this.debugLog('[processEvent] Comparing constraint:', constraint, '->', targetKey, 'vs', normalizedPressedKey, 'code:', e.code);

                    // Match against key (normalized)
                    if (targetKey === normalizedPressedKey) {
                        match = true;
                        break;
                    }

                    // Fallback: match against code (e.g. 'h' matches 'KeyH')
                    // This handles cases where modifiers change the key value (e.g. Alt+H -> ˙)
                    if (e.code && e.code.toLowerCase() === `key${targetKey}`) {
                        match = true;
                        break;
                    }
                }
                if (!match) {
                    this.debugLog('[processEvent] No key match found.');
                    return;
                }
            }
        }

        // --- 3. Performance Modifiers ---
        const debounceMod = modifiers.find(m => m.startsWith('debounce'));
        const throttleMod = modifiers.find(m => m.startsWith('throttle'));

        const elementId = element.id || this.getUniqueId(element);
        const eventKey = `${elementId}-${eventType}-${handlerName}`;

        if (debounceMod) {
            const duration = this.parseDuration(modifiers, 250);

            if (this.debouncers.has(eventKey)) {
                window.clearTimeout(this.debouncers.get(eventKey));
            }

            const timer = window.setTimeout(() => {
                this.debouncers.delete(eventKey);
                this.dispatchEvent(element, eventType, handlerName, e, explicitArgs);
            }, duration);

            this.debouncers.set(eventKey, timer);
            return;
        }

        if (throttleMod) {
            const duration = this.parseDuration(modifiers, 250);
            if (this.throttlers.has(eventKey)) return;

            this.throttlers.set(eventKey, Date.now());
            // Execute immediately
            this.dispatchEvent(element, eventType, handlerName, e, explicitArgs);

            window.setTimeout(() => {
                this.throttlers.delete(eventKey);
            }, duration);
            return;
        }

        // Direct dispatch
        this.dispatchEvent(element, eventType, handlerName, e, explicitArgs);
    }

    /**
     * Extract data and send event.
     */
    private dispatchEvent(element: HTMLElement, eventType: string, handler: string, e: Event, explicitArgs?: any[]): void {
        // Merge explicit args (from JSON) into args payload
        let args: Record<string, any> = {};
        if (explicitArgs && explicitArgs.length > 0) {
            explicitArgs.forEach((val: any, i: number) => {
                args[`arg${i}`] = val;
            });
        } else {
            args = this.getArgs(element);
        }

        const eventData: EventData = {
            type: eventType,
            id: element.id,
            args: args
        };

        // Extract specific data based on element type
        if (element instanceof HTMLInputElement) {
            eventData.value = element.value;
            if (element.type === 'checkbox' || element.type === 'radio') {
                eventData.checked = element.checked;
            }
        } else if (element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement) {
            eventData.value = element.value;
        }

        // Extract Key data
        if (e instanceof KeyboardEvent) {
            eventData.key = e.key;
            eventData.keyCode = e.keyCode;
        }

        // Extract Form Data for submit
        if (eventType === 'submit' && element instanceof HTMLFormElement) {
            const formData = new FormData(element);
            const data: Record<string, any> = {};
            formData.forEach((value, key) => {
                if (!(value instanceof File)) {
                    data[key] = value.toString();
                }
            });
            eventData.formData = data;
        }

        this.app.sendEvent(handler, eventData);
    }

    private parseDuration(modifiers: string[], defaultDuration: number): number {
        const debounceIdx = modifiers.findIndex(m => m.startsWith('debounce'));
        const throttleIdx = modifiers.findIndex(m => m.startsWith('throttle'));
        const idx = debounceIdx !== -1 ? debounceIdx : throttleIdx;

        if (idx !== -1 && modifiers[idx + 1]) {
            const next = modifiers[idx + 1];
            if (next.endsWith('ms')) {
                const val = parseInt(next);
                if (!isNaN(val)) return val;
            }
        }

        // Support hyphenated: debounce-500ms
        const mod = modifiers[idx];
        if (mod && mod.includes('-')) {
            const parts = mod.split('-');
            const val = parseInt(parts[1]);
            if (!isNaN(val)) return val;
        }

        return defaultDuration;
    }

    private getUniqueId(element: HTMLElement): string {
        if (!element.id) {
            element.id = 'pywire-uid-' + Math.random().toString(36).substr(2, 9);
        }
        return element.id;
    }

    private getArgs(element: Element): Record<string, unknown> {
        const args: Record<string, unknown> = {};
        if (element instanceof HTMLElement) {
            for (const key in element.dataset) {
                if (key.startsWith('arg')) {
                    try {
                        args[key] = JSON.parse(element.dataset[key] || 'null');
                    } catch (e) {
                        args[key] = element.dataset[key];
                    }
                }
            }
        }
        return args;
    }
}
