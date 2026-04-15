/**
 * Base transport interface for all transport implementations.
 */
export interface Transport {
  /** Connect to the server */
  connect(): Promise<void>

  /** Send a message to the server */
  send(message: object): void

  /** Register a message handler */
  onMessage(handler: MessageHandler): void

  /** Register a status change handler */
  onStatusChange(handler: (connected: boolean) => void): void

  /** Disconnect from the server */
  disconnect(): void

  /** Check if connected */
  isConnected(): boolean

  /** Set session ID for reconnection routing (e.g. Durable Objects) */
  setSessionId(sessionId: string): void

  /** Transport name for debugging */
  readonly name: string
}

export type MessageHandler = (message: ServerMessage) => void

export interface StackFrame {
  filename: string
  lineno: number
  name: string
  line: string
  colno?: number // Python 3.11+ column start
  end_colno?: number // Python 3.11+ column end
}

export interface Command {
  cmd: string
  refId: string
  args?: Record<string, unknown>
}

export interface ServerMessage {
  type:
    | 'update'
    | 'reload'
    | 'error'
    | 'console'
    | 'error_trace'
    | 'init'
    | 'navigate'
    | 'init_ack'
    | 'ping'
  html?: string
  regions?: Array<{ region: string; html: string }>
  error?: string
  level?: 'info' | 'warn' | 'error'
  lines?: string[]
  trace?: StackFrame[]
  version?: string
  path?: string
  commands?: Command[]
  session_id?: string
  session_restored?: boolean
}

export interface NavigateMessage {
  type: 'navigate'
  path: string
}

export interface InitMessage {
  type: 'init'
  version: string
}

export interface ConsoleMessage {
  type: 'console'
  level: 'info' | 'warn' | 'error'
  lines: string[]
}

export type ClientMessage =
  | EventMessage
  | RelocateMessage
  | RefSyncMessage
  | RefPropertySyncMessage
  | InitClientMessage

export interface InitClientMessage {
  type: 'init'
  path: string
  session_id?: string
}

export interface EventMessage {
  type: 'event'
  handler: string
  path: string
  data: EventData
}

export interface RelocateMessage {
  type: 'relocate'
  path: string
}

export interface RefSyncMessage {
  type: 'ref_sync'
  refId: string
  value: unknown
}

export interface RefPropertySyncMessage {
  type: 'ref_sync'
  refId: string
  property: string
  value: unknown
}

export interface EventData {
  type: string
  id?: string
  name?: string
  tagName?: string
  value?: unknown
  checked?: boolean
  inputType?: string
  formData?: Record<string, unknown>
  args?: Record<string, unknown>
  // Keyboard
  key?: string
  code?: string
  keyCode?: number
  // Mouse/Pointer
  clientX?: number
  clientY?: number
  offsetX?: number
  offsetY?: number
  pageX?: number
  pageY?: number
  screenX?: number
  screenY?: number
  button?: number
  buttons?: number
  // Custom events
  detail?: unknown
  // Modifiers
  altKey?: boolean
  ctrlKey?: boolean
  metaKey?: boolean
  shiftKey?: boolean
  [key: string]: unknown
}

/**
 * Abstract base class providing common transport functionality.
 */
export abstract class BaseTransport implements Transport {
  protected messageHandlers: MessageHandler[] = []
  protected statusHandlers: ((connected: boolean) => void)[] = []
  protected connected = false

  abstract readonly name: string
  abstract connect(): Promise<void>
  abstract send(message: object): void
  abstract disconnect(): void

  setSessionId(_sessionId: string): void {
    // Default no-op; WebSocketTransport overrides to append ?session= to URL
  }

  onMessage(handler: MessageHandler): void {
    this.messageHandlers.push(handler)
  }

  onStatusChange(handler: (connected: boolean) => void): void {
    this.statusHandlers.push(handler)
  }

  isConnected(): boolean {
    return this.connected
  }

  protected notifyHandlers(message: ServerMessage): void {
    for (const handler of this.messageHandlers) {
      try {
        handler(message)
      } catch (e) {
        console.error('PyWire: Error in message handler', e)
      }
    }
  }

  protected notifyStatus(connected: boolean): void {
    if (this.connected === connected) return
    this.connected = connected
    for (const handler of this.statusHandlers) {
      try {
        handler(connected)
      } catch (e) {
        console.error('PyWire: Error in status handler', e)
      }
    }
  }
}
