import { PyWireApp, ServerMessage } from '../core';
import { StatusOverlay } from './status-overlay';
import { ErrorTraceHandler } from './error-trace';

/**
 * Development-mode PyWire Application.
 * Extends core app with:
 * - Connection status overlay
 * - Error trace handling with source loading
 * - Enhanced console output
 */
export class PyWireDevApp extends PyWireApp {
    private overlay: StatusOverlay | null = null;
    private errorHandler: ErrorTraceHandler;

    constructor(config = {}) {
        super(config);
        this.errorHandler = new ErrorTraceHandler();
    }

    async init(): Promise<void> {
        // Create overlay before init so status changes are captured
        this.overlay = new StatusOverlay();

        await super.init();
    }

    /**
     * Handle connection status changes with UI overlay.
     */
    protected handleStatusChange(connected: boolean): void {
        super.handleStatusChange(connected);
        if (this.overlay) {
            this.overlay.update(connected);
        }
    }

    /**
     * Navigate with offline feedback.
     */
    navigateTo(path: string): void {
        if (!this.isConnected) {
            console.warn('PyWire: Navigation blocked - Offline');
            if (this.overlay) {
                this.overlay.showNavigationBlocked();
            }
            return;
        }

        super.navigateTo(path);
    }

    /**
     * Handle incoming server messages with enhanced error trace support.
     */
    protected async handleMessage(msg: ServerMessage): Promise<void> {
        switch (msg.type) {
            case 'error_trace':
                if (msg.trace) {
                    await this.errorHandler.handle(msg.error || 'Unknown Error', msg.trace);
                }
                return;

            case 'console':
                // Enhanced console output with grouping
                if (msg.lines && msg.lines.length > 0) {
                    const prefix = 'PyWire Server:';
                    const joined = msg.lines.join('\n');
                    if (msg.level === 'error') {
                        console.group(prefix + ' Error');
                        console.error(joined);
                        console.groupEnd();
                    } else if (msg.level === 'warn') {
                        console.groupCollapsed(prefix + ' Warning');
                        console.warn(joined);
                        console.groupEnd();
                    } else {
                        if (msg.lines.length === 1) {
                            console.log(prefix, joined);
                        } else {
                            console.groupCollapsed(prefix + ' Log');
                            console.log(joined);
                            console.groupEnd();
                        }
                    }
                }
                return;

            default:
                await super.handleMessage(msg);
        }
    }
}
