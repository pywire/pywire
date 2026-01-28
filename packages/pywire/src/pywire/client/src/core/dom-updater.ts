/**
 * DOM Updater using morphdom for efficient DOM diffing.
 */
import morphdom from 'morphdom';

interface FocusState {
    /** CSS selector to find the element */
    selector: string;
    /** Element ID if available */
    id: string | null;
    tagName: string;
    selectionStart: number | null;
    selectionEnd: number | null;
    scrollTop: number;
    scrollLeft: number;
    value: string;
}

export class DOMUpdater {
    /**
     * Flag to indicate DOM is being updated.
     * Event handlers should check this to avoid triggering events during updates.
     */
    static isUpdating = false;

    private debug: boolean;

    constructor(debug: boolean = false) {
        this.debug = debug;
    }

    /**
     * Generate a stable key for an element.
     * Used by morphdom to match elements between old and new DOM.
     */
    private getNodeKey(node: Node): string | undefined {
        if (!(node instanceof HTMLElement)) return undefined;

        // 1. Use data-on-* handler as key FIRST (stable across renders)
        for (const attr of node.attributes) {
            if (attr.name.startsWith('data-on-')) {
                const key = `${node.tagName}-${attr.name}-${attr.value}`;
                return key;
            }
        }

        // 2. Use explicit ID (but skip client-generated pywire-uid-* IDs)
        if (node.id && !node.id.startsWith('pywire-uid-')) {
            return node.id;
        }

        // 3. Use name attribute for form elements
        if (node instanceof HTMLInputElement ||
            node instanceof HTMLSelectElement ||
            node instanceof HTMLTextAreaElement) {
            if (node.name) {
                return `${node.tagName}-name-${node.name}`;
            }
        }

        // 4. For other elements, no key (morphdom will use position-based matching)
        return undefined;
    }

    /**
     * Generate a selector to find an element
     */
    private getElementSelector(el: Element): string {
        if (el.id) return `#${el.id}`;

        // Build a path-based selector
        const path: string[] = [];
        let current: Element | null = el;

        while (current && current !== document.body && path.length < 5) {
            let selector = current.tagName.toLowerCase();

            // Add distinguishing attributes
            if (current.id) {
                selector = `#${current.id}`;
                path.unshift(selector);
                break; // ID is unique enough
            }

            // Use name for form elements
            if (current instanceof HTMLInputElement ||
                current instanceof HTMLSelectElement ||
                current instanceof HTMLTextAreaElement) {
                if (current.name) {
                    selector += `[name="${current.name}"]`;
                }
            }

            // Use data-on-* for event elements
            for (const attr of current.attributes) {
                if (attr.name.startsWith('data-on-')) {
                    selector += `[${attr.name}="${attr.value}"]`;
                    break;
                }
            }

            // Add nth-child for disambiguation
            if (current.parentElement) {
                const sibs = Array.from(current.parentElement.children);
                const sameTags = sibs.filter(s => s.tagName === current!.tagName);
                if (sameTags.length > 1) {
                    const idx = sameTags.indexOf(current) + 1;
                    selector += `:nth-of-type(${idx})`;
                }
            }

            path.unshift(selector);
            current = current.parentElement;
        }

        return path.join(' > ');
    }

    /**
     * Capture the current focus state before updating.
     */
    private captureFocusState(): FocusState | null {
        const active = document.activeElement;
        if (!active || active === document.body || active === document.documentElement) return null;

        const state: FocusState = {
            selector: this.getElementSelector(active),
            id: active.id || null,
            tagName: active.tagName,
            selectionStart: null,
            selectionEnd: null,
            scrollTop: 0,
            scrollLeft: 0,
            value: ''
        };

        if (active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement) {
            state.selectionStart = active.selectionStart;
            state.selectionEnd = active.selectionEnd;
            state.scrollTop = active.scrollTop;
            state.scrollLeft = active.scrollLeft;
            state.value = active.value;
        }

        return state;
    }

    /**
     * Restore focus state after updating.
     */
    private restoreFocusState(state: FocusState | null): void {
        if (!state) return;

        // Try to find by ID first, then by selector
        let el: Element | null = null;
        if (state.id) {
            el = document.getElementById(state.id);
        }
        if (!el && state.selector) {
            try {
                el = document.querySelector(state.selector);
            } catch (e) {
                // Invalid selector, skip
            }
        }

        if (!el) return;

        // Restore focus
        (el as HTMLElement).focus();

        // Restore selection/caret position
        if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
            // Restore value if it matches what we captured
            if (state.value && el.value !== state.value) {
                el.value = state.value;
            }

            if (state.selectionStart !== null && state.selectionEnd !== null) {
                try {
                    el.setSelectionRange(state.selectionStart, state.selectionEnd);
                } catch (e) {
                    // Some input types (date, number) don't support setSelectionRange
                }
            }
            el.scrollTop = state.scrollTop;
            el.scrollLeft = state.scrollLeft;
        }
    }

    /**
     * Update the DOM with new HTML content.
     */
    update(newHtml: string): void {
        // Set flag to suppress focus/blur events during update
        DOMUpdater.isUpdating = true;
        if (this.debug) {
            console.log('[DOMUpdater] Starting update, isUpdating =', DOMUpdater.isUpdating);
        }

        try {
            // Capture focus before morphdom runs
            const focusState = this.captureFocusState();

            // Capture all form element states
            const formStates = new Map<string, { value: string; checked?: boolean; selectedIndex?: number }>();
            document.querySelectorAll('input, select, textarea').forEach((el, idx) => {
                const key = this.getNodeKey(el) || `form-el-${idx}`;
                if (el instanceof HTMLInputElement) {
                    formStates.set(key, {
                        value: el.value,
                        checked: el.type === 'checkbox' || el.type === 'radio' ? el.checked : undefined
                    });
                } else if (el instanceof HTMLSelectElement) {
                    formStates.set(key, { value: el.value, selectedIndex: el.selectedIndex });
                } else if (el instanceof HTMLTextAreaElement) {
                    formStates.set(key, { value: el.value });
                }
            });

            if (morphdom) {
                try {
                    morphdom(document.documentElement, newHtml, {
                        // Custom key function for stable element matching
                        getNodeKey: (node: Node) => this.getNodeKey(node),

                        onBeforeElUpdated: (fromEl, toEl) => {
                            // Transfer ALL relevant state from old element to new element

                            // Input/Textarea: preserve value ONLY if they are broadly similar
                            // (e.g. user is still typing or deleted a few chars).
                            // If the server sends a completely different value, let it win.
                            if (fromEl instanceof HTMLInputElement && toEl instanceof HTMLInputElement) {
                                if (fromEl.type === 'checkbox' || fromEl.type === 'radio') {
                                    toEl.checked = fromEl.checked;
                                } else {
                                    const s = toEl.value || '';
                                    const c = fromEl.value || '';
                                    if (c.startsWith(s) || s.startsWith(c)) {
                                        toEl.value = c;
                                    }
                                }
                            }

                            if (fromEl instanceof HTMLTextAreaElement && toEl instanceof HTMLTextAreaElement) {
                                const s = toEl.value || '';
                                const c = fromEl.value || '';
                                if (c.startsWith(s) || s.startsWith(c)) {
                                    toEl.value = c;
                                }
                            }

                            // Select: preserve selected option
                            if (fromEl instanceof HTMLSelectElement && toEl instanceof HTMLSelectElement) {
                                // Preserve by value (more robust than index)
                                if (fromEl.value && Array.from(toEl.options).some(o => o.value === fromEl.value)) {
                                    toEl.value = fromEl.value;
                                } else if (fromEl.selectedIndex >= 0 && fromEl.selectedIndex < toEl.options.length) {
                                    toEl.selectedIndex = fromEl.selectedIndex;
                                }
                            }

                            // Preserve client-generated IDs (vital for debouncers/throttlers that key off ID)
                            if (fromEl.id && fromEl.id.startsWith('pywire-uid-') && !toEl.id) {
                                toEl.id = fromEl.id;
                            }

                            return true;
                        },

                        onBeforeNodeDiscarded: () => true
                    });
                } catch (e) {
                    console.error('Morphdom failed:', e);
                    document.open();
                    document.write(newHtml);
                    document.close();
                }

                // Restore focus after morphdom completes
                this.restoreFocusState(focusState);
            } else {
                document.open();
                document.write(newHtml);
                document.close();
            }
        } finally {
            // Clear flag after a microtask to ensure all focus events are suppressed
            setTimeout(() => {
                DOMUpdater.isUpdating = false;
            }, 0);
        }
    }
}

