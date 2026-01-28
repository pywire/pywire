/**
 * Connection status overlay for development mode.
 * Shows a toast-style notification when connection is lost.
 */
export class StatusOverlay {
    private element: HTMLElement | null = null;

    constructor() {
        this.create();
    }

    private create(): void {
        this.element = document.createElement('div');
        this.element.style.cssText = `
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: rgba(0, 0, 0, 0.8);
            color: white;
            padding: 10px 20px;
            border-radius: 5px;
            font-family: system-ui, -apple-system, sans-serif;
            font-size: 14px;
            z-index: 10000;
            display: none;
            transition: opacity 0.3s;
            pointer-events: none;
        `;
        document.body.appendChild(this.element);
    }

    /**
     * Update overlay based on connection status.
     */
    update(connected: boolean): void {
        if (!this.element) return;

        if (connected) {
            this.element.style.display = 'none';
        } else {
            this.element.textContent = 'Connection Lost - Reconnecting...';
            this.element.style.display = 'block';
            this.element.style.backgroundColor = 'rgba(0, 0, 0, 0.8)';
        }
    }

    /**
     * Show a temporary navigation-blocked message.
     */
    showNavigationBlocked(): void {
        if (!this.element) return;

        this.element.style.backgroundColor = 'rgba(200, 0, 0, 0.9)';
        this.element.textContent = 'Cannot navigate - Offline';
        this.element.style.display = 'block';

        setTimeout(() => {
            if (this.element) {
                this.element.style.backgroundColor = 'rgba(0, 0, 0, 0.8)';
            }
        }, 1500);
    }
}
