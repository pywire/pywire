import { TransportManager, TransportConfig } from './transport-manager'
import { version as clientVersion } from '../../package.json'
import { DOMUpdater } from './dom-updater'
import {
  ServerMessage,
  ClientMessage,
  EventData,
  RelocateMessage,
  Command,
  RefSyncMessage,
  RefPropertySyncMessage,
  InitClientMessage,
} from './transports'
import { UnifiedEventHandler } from '../events/handler'
import { RefManager } from './ref-manager'
import { ReconnectOverlay } from './reconnect-overlay'
import { logger } from './logger'

export interface PyWireConfig extends TransportConfig {
  /** Auto-initialize on DOMContentLoaded */
  autoInit?: boolean
  /** Enable verbose debug logging */
  debug?: boolean
  /** Maximum reconnection attempts before giving up (default 10) */
  reconnectMaxAttempts?: number
  /** Show reconnection overlay on disconnect (default true) */
  reconnectOverlay?: boolean
}

const DEFAULT_CONFIG: PyWireConfig = {
  autoInit: true,
  enableWebTransport: false,
  enableWebSocket: true,
  enableHTTP: true,
  debug: false,
}

/**
 * Core PyWire Application class.
 * Provides transport, DOM updates, SPA navigation, and event handling.
 * Dev-only features (status overlay, error traces) are in the dev bundle.
 */
export class PyWireApp {
  protected transport: TransportManager
  protected updater: DOMUpdater
  protected eventHandler: UnifiedEventHandler
  protected refManager: RefManager
  protected reconnectOverlay: ReconnectOverlay
  protected initialized = false
  protected config: PyWireConfig
  protected siblingPaths: string[] = []
  protected pathRegexes: RegExp[] = []
  protected allPaths: string[] = []
  protected allPathRegexes: RegExp[] = []
  protected pjaxEnabled = false
  protected staticPath: string = '/static'
  protected isConnected = false
  protected sessionId: string | null = null
  private intentionalDisconnect = false
  /**
   * Tracks the target path of a pending PJAX navigation.
   * Set before sending a relocate message, cleared after the resulting
   * update is applied so we can dispatch `pywire:navigate`.
   */
  protected pendingNavigationPath: string | null = null

  constructor(config: Partial<PyWireConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config }
    logger.setDebug(!!this.config.debug)
    this.transport = new TransportManager(this.config)
    this.updater = new DOMUpdater(this.config.debug)
    this.eventHandler = new UnifiedEventHandler(this)
    this.reconnectOverlay = new ReconnectOverlay({
      maxAttempts: this.config.reconnectMaxAttempts,
      enabled: this.config.reconnectOverlay,
    })
    this.refManager = new RefManager(
      (refId, value) => {
        if (this.isConnected) {
          const msg: RefSyncMessage = {
            type: 'ref_sync',
            refId,
            value,
          }
          this.transport.send(msg)
        }
      },
      (refId, property, value) => {
        if (this.isConnected) {
          const msg: RefPropertySyncMessage = {
            type: 'ref_sync',
            refId,
            property,
            value,
          }
          this.transport.send(msg)
        }
      }
    )
  }

  getConfig(): PyWireConfig {
    return this.config
  }

  getRefManager(): RefManager {
    return this.refManager
  }

  /**
   * Initialize the PyWire application.
   */
  async init(): Promise<void> {
    if (this.initialized) return
    this.initialized = true

    // Setup message handling
    this.transport.onMessage((msg) => this.handleMessage(msg))
    this.transport.onStatusChange((connected) => this.handleStatusChange(connected))

    // Connect transport with fallback
    try {
      await this.transport.connect()
    } catch (e) {
      logger.error('PyWire: Failed to connect:', e)
    }

    // Load SPA metadata and setup navigation
    this.loadSPAMetadata()
    this.setupSPANavigation()

    // Setup event interception via UnifiedEventHandler
    this.eventHandler.init()
    this.refManager.init()

    logger.log(
      `PyWire: Initialized (transport: ${this.transport.getActiveTransport()}, spa_paths: ${this.siblingPaths.length}, pjax: ${this.pjaxEnabled})`
    )
  }

  /**
   * Handle connection status changes. Override in dev bundle for UI.
   */
  protected handleStatusChange(connected: boolean): void {
    this.isConnected = connected

    if (connected) {
      // Send init message to register this client and setup page instance
      const initMsg: InitClientMessage = {
        type: 'init',
        path: window.location.pathname + window.location.search,
      }
      // Include session_id on reconnect to restore state from session store
      if (this.sessionId) {
        initMsg.session_id = this.sessionId
      }
      this.transport.send(initMsg)
    } else if (!this.intentionalDisconnect) {
      // Show reconnect overlay when connection drops unexpectedly
      this.reconnectOverlay.show()
    }
  }

  /**
   * Load SPA navigation metadata from injected script tag.
   */
  protected loadSPAMetadata(): void {
    const metaScript = document.getElementById('_pywire_spa_meta')
    if (metaScript) {
      try {
        const meta = JSON.parse(metaScript.textContent || '{}')
        this.siblingPaths = meta.sibling_paths || []
        this.allPaths = meta.all_paths || []
        this.pjaxEnabled = !!meta.enable_pjax
        this.staticPath = meta.static_path || '/static'
        if (meta.debug !== undefined) {
          this.config.debug = !!meta.debug
          logger.setDebug(this.config.debug)
        }
        // Apply reconnect config from server metadata
        if (meta.reconnect_max_attempts !== undefined) {
          this.config.reconnectMaxAttempts = meta.reconnect_max_attempts
          this.reconnectOverlay = new ReconnectOverlay({
            maxAttempts: meta.reconnect_max_attempts,
            enabled: meta.reconnect_overlay ?? this.config.reconnectOverlay,
          })
        } else if (meta.reconnect_overlay !== undefined) {
          this.reconnectOverlay = new ReconnectOverlay({
            maxAttempts: this.config.reconnectMaxAttempts,
            enabled: meta.reconnect_overlay,
          })
        }
        // Convert path patterns to regexes for matching
        this.pathRegexes = this.siblingPaths.map((p) => this.patternToRegex(p))
        this.allPathRegexes = this.allPaths.map((p) => this.patternToRegex(p))
      } catch (e) {
        logger.warn('PyWire: Failed to parse SPA metadata', e)
      }
    }
  }

  /**
   * Convert route pattern like '/a/:id' to regex.
   */
  protected patternToRegex(pattern: string): RegExp {
    // Escape special regex chars except for our placeholders
    let regex = pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&')
    // Replace :param:type or :param with capture groups
    regex = regex.replace(/:(\w+)(:\w+)?/g, '([^/]+)')
    // Replace {param:type} or {param} with capture groups
    regex = regex.replace(/\{(\w+)(:\w+)?\}/g, '([^/]+)')
    return new RegExp(`^${regex}$`)
  }

  /**
   * Check if a path matches any sibling path pattern.
   */
  protected isSiblingPath(path: string): boolean {
    return this.pathRegexes.some((regex) => regex.test(path))
  }

  /**
   * Check if a path matches any known wire page route.
   */
  protected isWirePath(path: string): boolean {
    return this.allPathRegexes.some((regex) => regex.test(path))
  }

  /**
   * Setup SPA navigation for sibling paths.
   */
  protected setupSPANavigation(): void {
    // Handle browser back/forward — dispatch beforenavigate then request new page
    window.addEventListener('popstate', () => {
      const targetPath = window.location.pathname + window.location.search
      // For popstate the browser has already updated the URL, so "from" is unknown.
      // We pass the target as both from/to; listeners should use `to` primarily.
      document.dispatchEvent(
        new CustomEvent('pywire:beforenavigate', {
          bubbles: true,
          detail: { from: targetPath, to: targetPath },
        })
      )
      this.sendRelocate(targetPath)
    })

    if (this.siblingPaths.length === 0 && !this.pjaxEnabled) return

    // Intercept link clicks
    document.addEventListener('click', (e) => {
      const link = (e.target as Element).closest('a[href]') as HTMLAnchorElement | null
      if (!link) return

      // Let the browser handle modified clicks (new tab, new window, etc.)
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return

      // Only intercept same-origin links
      if (link.origin !== window.location.origin) return

      // Ignore special links
      if (link.hasAttribute('download') || link.target === '_blank') return

      // Check if matches criteria
      let shouldIntercept = false

      if (this.pjaxEnabled) {
        shouldIntercept = this.isWirePath(link.pathname)
      } else if (this.isSiblingPath(link.pathname)) {
        shouldIntercept = true
      }

      // Never PJAX-navigate to static assets or internal PyWire routes
      if (this.staticPath.length > 1 && link.pathname.startsWith(this.staticPath + '/')) {
        shouldIntercept = false
      }
      if (link.pathname.startsWith('/_pywire/')) {
        shouldIntercept = false
      }

      // NO-SPA: Check for data-pw-reload attribute
      if (link.hasAttribute('data-pw-reload')) {
        shouldIntercept = false
      }

      if (shouldIntercept) {
        e.preventDefault()
        this.navigateTo(link.pathname + link.search)
      }
    })
  }

  /**
   * Navigate to a path using SPA navigation.
   *
   * Dispatches `pywire:beforenavigate` on `document` before the navigation
   * fetch starts. Listeners can use this to tear down page-specific state
   * (e.g., remove global event listeners, cancel timers).
   *
   * After the server responds and the DOM is updated, `pywire:navigate` is
   * dispatched (see {@link handleMessage}).
   */
  navigateTo(path: string): void {
    if (!this.isConnected) {
      logger.warn('PyWire: Navigation blocked - Offline')
      return
    }

    const currentPath = window.location.pathname + window.location.search

    /**
     * **pywire:beforenavigate** — fired on `document` before a PJAX navigation fetch.
     *
     * @detail.from  The path being navigated away from.
     * @detail.to    The target path.
     *
     * Use cases:
     * - Remove global event listeners (resize, scroll, keydown) added by the current page.
     * - Cancel pending timers or animation frames.
     * - Persist unsaved form data to sessionStorage.
     */
    document.dispatchEvent(
      new CustomEvent('pywire:beforenavigate', {
        bubbles: true,
        detail: { from: currentPath, to: path },
      })
    )

    history.pushState({}, '', path)
    this.sendRelocate(path)
  }

  /**
   * Send relocate message to server and mark a navigation as pending.
   */
  protected sendRelocate(path: string): void {
    this.pendingNavigationPath = path
    const message: RelocateMessage = {
      type: 'relocate',
      path,
    }
    this.transport.send(message)
  }

  /**
   * Send an event to the server.
   */
  sendEvent(handler: string, data: EventData): void {
    const message: ClientMessage = {
      type: 'event',
      handler,
      path: window.location.pathname + window.location.search,
      data,
    }
    this.transport.send(message)
  }

  /**
   * Handle incoming server message. Override in dev bundle for error_trace.
   */
  protected async handleMessage(msg: ServerMessage): Promise<void> {
    switch (msg.type) {
      case 'update': {
        // Capture and clear pending navigation before applying the update,
        // so we can dispatch pywire:navigate after the DOM settles.
        const navPath = this.pendingNavigationPath
        this.pendingNavigationPath = null

        if (msg.commands && msg.commands.length > 0) {
          msg.commands.forEach((cmd: Command) => {
            if (cmd.cmd === 'set_cookie' || cmd.cmd === 'delete_cookie') {
              this.handleCookieCommand(cmd)
            } else if (cmd.cmd === 'dispatch') {
              this.handleDispatchCommand(cmd)
            } else {
              this.refManager.executeCommand(cmd)
            }
          })
        }
        if (msg.regions && msg.regions.length > 0) {
          msg.regions.forEach((update: { region: string; html: string }) => {
            this.updater.updateRegion(update.region, update.html)
          })
          this.eventHandler.refreshListeners()
        } else if (msg.html) {
          this.updater.update(msg.html)
          this.eventHandler.refreshListeners()
        }

        // If this update was triggered by a PJAX navigation (relocate),
        // dispatch the post-navigation event after morphdom + scripts complete.
        if (navPath) {
          /**
           * **pywire:navigate** — fired on `document` after a PJAX navigation
           * completes and the new page is fully rendered (morphdom applied,
           * scripts executed).
           *
           * Unlike `pywire:postupdate`, which fires on ANY DOM update (including
           * partial state/region updates), this event fires only for full-page
           * SPA navigations.
           *
           * @detail.path  The path that was navigated to.
           *
           * Use cases:
           * - Analytics pageview tracking (e.g., `gtag('event', 'page_view', ...)`).
           * - Scroll-to-top or focus management after navigation.
           * - Initializing page-specific libraries or widgets.
           */
          document.dispatchEvent(
            new CustomEvent('pywire:navigate', {
              bubbles: true,
              detail: { path: navPath },
            })
          )
        }
        break
      }

      case 'reload':
        logger.log('PyWire: Reloading...')
        window.location.reload()
        break

      case 'error':
        logger.error('PyWire: Server error:', msg.error)
        break

      case 'error_trace':
        // In core bundle, just log the error (no source loading)
        logger.error('PyWire: Error:', msg.error)
        break

      case 'console':
        if (msg.lines && msg.lines.length > 0) {
          const prefix = 'PyWire Server:'
          const joined = msg.lines.join('\n')
          if (msg.level === 'error') {
            logger.error(prefix, joined)
          } else if (msg.level === 'warn') {
            logger.warn(prefix, joined)
          } else {
            logger.log(prefix, joined)
          }
        }
        break

      case 'init_ack':
        // Detect expired session: client had a session_id but server couldn't restore it
        if (msg.session_restored === false && this.sessionId !== null) {
          this.showSessionExpiredNotification()
        }
        // Store session ID for reconnection state restoration
        if (msg.session_id) {
          this.sessionId = msg.session_id
        }
        // Hide reconnect overlay — state has been synced successfully
        this.reconnectOverlay.hide()
        logger.log('PyWire: Application ready')
        break

      case 'init':
        logger.log(`PyWire Client v${clientVersion} • Server v${msg.version}`)
        break

      case 'navigate':
        if (msg.path) {
          logger.log('PyWire: Navigating to', msg.path)
          this.navigateTo(msg.path)
        }
        break

      default:
        logger.warn('PyWire: Unknown message type', msg)
    }
  }

  /**
   * Handle a cookie command from the server (set or delete).
   * Note: httponly cookies cannot be set via document.cookie.
   */
  protected handleCookieCommand(cmd: Command): void {
    const args = cmd.args as Record<string, string | number | boolean>
    if (cmd.cmd === 'set_cookie') {
      let cookie = `${args.key}=${encodeURIComponent(String(args.value || ''))}`
      if (args.path) cookie += `; path=${args.path}`
      if (args.domain) cookie += `; domain=${args.domain}`
      if (args.max_age !== undefined && args.max_age !== null) cookie += `; max-age=${args.max_age}`
      if (args.secure) cookie += '; secure'
      if (args.samesite) cookie += `; samesite=${args.samesite}`
      document.cookie = cookie
    } else if (cmd.cmd === 'delete_cookie') {
      let cookie = `${args.key}=; max-age=0`
      if (args.path) cookie += `; path=${args.path}`
      if (args.domain) cookie += `; domain=${args.domain}`
      document.cookie = cookie
    }
  }

  /**
   * Show a non-intrusive toast notification when the session has expired.
   * Auto-dismisses after 5 seconds or on click.
   */
  protected showSessionExpiredNotification(): void {
    const toast = document.createElement('div')
    toast.textContent = 'Your session has expired. The page has been reset.'
    toast.setAttribute('role', 'alert')
    toast.style.cssText = `
      position: fixed;
      top: 20px;
      left: 50%;
      transform: translateX(-50%);
      background: rgba(0, 0, 0, 0.85);
      color: white;
      padding: 12px 24px;
      border-radius: 6px;
      font-family: system-ui, -apple-system, sans-serif;
      font-size: 14px;
      z-index: 10001;
      cursor: pointer;
      opacity: 0;
      transition: opacity 0.3s;
      pointer-events: auto;
    `
    document.body.appendChild(toast)

    // Fade in
    requestAnimationFrame(() => {
      toast.style.opacity = '1'
    })

    const dismiss = () => {
      toast.style.opacity = '0'
      setTimeout(() => toast.remove(), 300)
    }

    toast.addEventListener('click', dismiss)
    setTimeout(dismiss, 5000)
  }

  /**
   * Handle a dispatch command from the server (custom DOM event).
   */
  protected handleDispatchCommand(cmd: Command): void {
    const { refId } = cmd
    const rawCmd = cmd as unknown as Record<string, unknown>
    const event = rawCmd.event as string
    const detail = rawCmd.detail ?? {}
    const bubbles = (rawCmd.bubbles as boolean) ?? true
    const serverHandled = (rawCmd.serverHandled as boolean) ?? false

    const target = refId ? document.querySelector(`[data-pw-ref="${refId}"]`) : document.body

    if (target) {
      const customEvent = new CustomEvent(event, {
        bubbles,
        detail,
      })
      // Mark the event so pywire's event handler skips re-sending it to the
      // server — the Python handler was already called server-side.
      if (serverHandled) {
        ;(customEvent as unknown as Record<string, unknown>).__pwServerHandled = true
      }
      target.dispatchEvent(customEvent)
    } else {
      logger.warn(`PyWire: dispatch '${event}' failed - ref '${refId}' not found in DOM`)
    }
  }

  /**
   * Get the current transport name.
   */
  getTransport(): string | null {
    return this.transport.getActiveTransport()
  }

  /**
   * Disconnect from the server.
   */
  disconnect(): void {
    this.intentionalDisconnect = true
    this.reconnectOverlay.hide()
    this.transport.disconnect()
  }
}
