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
import { logger } from './logger'

export interface PyWireConfig extends TransportConfig {
  /** Auto-initialize on DOMContentLoaded */
  autoInit?: boolean
  /** Enable verbose debug logging */
  debug?: boolean
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

  constructor(config: Partial<PyWireConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config }
    logger.setDebug(!!this.config.debug)
    this.transport = new TransportManager(this.config)
    this.updater = new DOMUpdater(this.config.debug)
    this.eventHandler = new UnifiedEventHandler(this)
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
    // Handle browser back/forward
    window.addEventListener('popstate', () => {
      this.sendRelocate(window.location.pathname + window.location.search)
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
   */
  navigateTo(path: string): void {
    if (!this.isConnected) {
      logger.warn('PyWire: Navigation blocked - Offline')
      return
    }

    history.pushState({}, '', path)
    this.sendRelocate(path)
  }

  /**
   * Send relocate message to server.
   */
  protected sendRelocate(path: string): void {
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
      case 'update':
        if (msg.commands && msg.commands.length > 0) {
          msg.commands.forEach((cmd: Command) => {
            if (cmd.cmd === 'set_cookie' || cmd.cmd === 'delete_cookie') {
              this.handleCookieCommand(cmd)
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
        break

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
        // Store session ID for reconnection state restoration
        if (msg.session_id) {
          this.sessionId = msg.session_id
        }
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
   * Get the current transport name.
   */
  getTransport(): string | null {
    return this.transport.getActiveTransport()
  }

  /**
   * Disconnect from the server.
   */
  disconnect(): void {
    this.transport.disconnect()
  }
}
