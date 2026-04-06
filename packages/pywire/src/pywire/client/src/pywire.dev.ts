/**
 * PyWire Dev Bundle Entry Point
 * Includes all core features plus development tools:
 * - Connection status overlay
 * - Error trace with source loading for DevTools
 * - Enhanced console output
 */
import { PyWireDevApp } from './dev/dev-app'

// Re-export core
export * from './core'

// Export dev-specific
export { PyWireDevApp } from './dev/dev-app'
export { StatusOverlay } from './dev/status-overlay'
export { ErrorTraceHandler } from './dev/error-trace'

// Auto-init with dev app
const app = new PyWireDevApp()

// Expose on window for dev tools and testing
;(window as unknown as Record<string, unknown>).pywire = app

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => app.init())
} else {
  app.init()
}

export { app }
