/**
 * PyWire Core Bundle Entry Point
 * Production-optimized client with minimal footprint.
 * Excludes dev features: status overlay, error trace with source loading.
 */
import { PyWireApp } from './core/app';

export { PyWireApp, PyWireConfig } from './core/app';
export { TransportManager, TransportConfig } from './core/transport-manager';
export { DOMUpdater } from './core/dom-updater';
export * from './core/transports';

// Auto-init
const app = new PyWireApp();

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => app.init());
} else {
    app.init();
}

export { app };
