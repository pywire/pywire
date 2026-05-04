import { BaseTransport, ServerMessage } from './base'
import { encode, decode } from '@msgpack/msgpack'
import { logger } from '../logger'
import { getMountPath } from '../mount-path'

const DEBUG_CONNECTION = false

/**
 * WebSocket transport implementation.
 */
export class WebSocketTransport extends BaseTransport {
  readonly name = 'WebSocket'

  private socket: WebSocket | null = null
  private reconnectAttempts = 0
  private maxReconnectAttempts = 10
  private maxReconnectDelay = 30000
  private shouldReconnect = true
  private gaveUp = false
  private readonly baseUrl: string
  private sessionId: string | null = null
  private lastMessageTime = 0
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private readonly heartbeatCheckMs = 5000
  private readonly deadConnectionMs = 40000
  private giveUpHandlers: (() => void)[] = []

  constructor(url?: string) {
    super()
    this.baseUrl = url || this.getDefaultUrl()
  }

  private getDefaultUrl(): string {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const mount = getMountPath()
    return `${protocol}//${window.location.host}${mount}/_pywire/ws`
  }

  private getConnectUrl(): string {
    if (this.sessionId) {
      return `${this.baseUrl}?session=${encodeURIComponent(this.sessionId)}`
    }
    return this.baseUrl
  }

  setSessionId(sessionId: string): void {
    this.sessionId = sessionId
  }

  setMaxReconnectAttempts(n: number): void {
    this.maxReconnectAttempts = n
  }

  onGiveUp(handler: () => void): void {
    this.giveUpHandlers.push(handler)
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        const url = this.getConnectUrl()
        if (DEBUG_CONNECTION) logger.log(`PyWire: Connecting WebSocket to ${url}`)
        this.socket = new WebSocket(url)
        this.socket.binaryType = 'arraybuffer'

        this.socket.onopen = () => {
          if (DEBUG_CONNECTION) logger.log('PyWire: WebSocket connected')
          this.lastMessageTime = Date.now()
          this.startHeartbeat()
          this.notifyStatus(true)
          this.reconnectAttempts = 0
          this.gaveUp = false
          resolve()
        }

        this.socket.onmessage = (event: MessageEvent) => {
          this.lastMessageTime = Date.now()
          try {
            const msg = decode(event.data) as ServerMessage
            if (msg.type === 'ping') {
              // Respond to server keep-alive ping with pong
              this.send({ type: 'pong' })
              return
            }
            this.notifyHandlers(msg)
          } catch (e) {
            logger.error('PyWire: Error parsing WebSocket message', e)
          }
        }

        this.socket.onclose = () => {
          if (DEBUG_CONNECTION) logger.log('PyWire: WebSocket disconnected')
          this.clearHeartbeat()
          this.notifyStatus(false)
          if (this.shouldReconnect) {
            this.scheduleReconnect()
          }
        }

        this.socket.onerror = () => {
          // WebSocket "error" events fire on every failed connect
          // attempt during reconnect backoff. Suppress them in that
          // path — the browser still prints its own native
          // "WebSocket connection to ... failed" line, and we'll log
          // a single warn() once we give up. Surface a real error
          // only on the *initial* connect (no successful open yet
          // and not mid-reconnect).
          if (!this.connected && this.reconnectAttempts === 0) {
            logger.warn('PyWire: WebSocket failed to connect')
            reject(new Error('WebSocket connection failed'))
          }
        }
      } catch (e) {
        reject(e)
      }
    })
  }

  send(message: object): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(encode(message))
    } else {
      logger.warn('PyWire: Cannot send message, WebSocket not open')
    }
  }

  disconnect(): void {
    this.shouldReconnect = false
    this.clearHeartbeat()
    if (this.socket) {
      this.socket.close()
      this.socket = null
    }
    this.notifyStatus(false)
  }

  forceReconnect(): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.close()
      return
    }
    // Reset reconnect budget on a manual force (network came back online,
    // user-initiated retry) so we resume attempts even after giving up.
    this.gaveUp = false
    this.shouldReconnect = true
    this.reconnectAttempts = 0
    this.scheduleReconnect()
  }

  private startHeartbeat(): void {
    this.clearHeartbeat()
    this.heartbeatTimer = setInterval(() => {
      if (Date.now() - this.lastMessageTime > this.deadConnectionMs) {
        logger.warn('PyWire: WebSocket heartbeat timeout, reconnecting...')
        this.socket?.close()
      }
    }, this.heartbeatCheckMs)
  }

  private clearHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      if (this.gaveUp) return
      this.gaveUp = true
      this.shouldReconnect = false
      logger.warn(
        `PyWire: Reconnection failed after ${this.maxReconnectAttempts} attempts; giving up`
      )
      for (const handler of this.giveUpHandlers) {
        try {
          handler()
        } catch (e) {
          logger.error('PyWire: Error in giveUp handler', e)
        }
      }
      return
    }

    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), this.maxReconnectDelay)
    logger.log(
      `PyWire: Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts + 1}/${this.maxReconnectAttempts})`
    )

    setTimeout(() => {
      if (!this.shouldReconnect) return
      this.reconnectAttempts++
      this.connect().catch(() => {
        // Reconnect will be scheduled again on close
      })
    }, delay)
  }
}
