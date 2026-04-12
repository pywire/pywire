import { Command } from './transports'
import { logger } from './logger'

type FileMeta = { name: string; size: number; type: string }
type ElementValue = string | number | boolean | FileMeta[]
type RectData = {
  x: number
  y: number
  width: number
  height: number
  top: number
  right: number
  bottom: number
  left: number
}
type FormFieldValue = string | string[] | FileMeta | FileMeta[]

function debounce(func: (...args: unknown[]) => unknown, wait: number) {
  let timeout: ReturnType<typeof setTimeout> | undefined
  return function (...args: unknown[]) {
    clearTimeout(timeout)
    timeout = setTimeout(() => func(...args), wait)
  }
}

/**
 * Manages element references and executes imperative commands from the server.
 */
export class RefManager {
  private pendingRectRequests = new Set<string>()
  private onSync?: (refId: string, value: ElementValue) => void
  private onPropertySync?: (refId: string, property: string, value: unknown) => void
  private observer: MutationObserver
  private observedElements = new WeakSet<HTMLElement>()

  constructor(
    onSync?: (refId: string, value: ElementValue) => void,
    onPropertySync?: (refId: string, property: string, value: unknown) => void
  ) {
    this.onSync = onSync
    this.onPropertySync = onPropertySync
    this.observer = new MutationObserver(this.handleMutations.bind(this))
  }

  init() {
    // Initial scan
    document
      .querySelectorAll('[data-pw-ref]')
      .forEach((el) => this.attachListeners(el as HTMLElement))

    // Observe DOM for new refs
    this.observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['data-pw-ref'],
    })
  }

  private handleMutations(mutations: MutationRecord[]) {
    for (const mutation of mutations) {
      if (mutation.type === 'childList') {
        mutation.addedNodes.forEach((node) => {
          if (node instanceof HTMLElement) {
            if (node.hasAttribute('data-pw-ref')) {
              this.attachListeners(node)
            }
            // Check children
            node
              .querySelectorAll('[data-pw-ref]')
              .forEach((el) => this.attachListeners(el as HTMLElement))
          }
        })
      } else if (mutation.type === 'attributes' && mutation.attributeName === 'data-pw-ref') {
        if (mutation.target instanceof HTMLElement) {
          this.attachListeners(mutation.target)
        }
      }
    }
  }

  private attachListeners(element: HTMLElement) {
    if (this.observedElements.has(element)) return
    this.observedElements.add(element)

    const refId = element.getAttribute('data-pw-ref')
    if (!refId || !this.onSync) return

    // Attach to input-like elements
    if (
      element instanceof HTMLInputElement ||
      element instanceof HTMLTextAreaElement ||
      element instanceof HTMLSelectElement
    ) {
      const handler = debounce(() => {
        const val = this.getElementValue(element)
        if (this.onSync && refId) {
          this.onSync(refId, val)
        }
      }, 250)

      element.addEventListener('input', handler)
      element.addEventListener('change', handler)
    }

    // Attach to media elements (<audio>, <video>)
    if (element instanceof HTMLMediaElement && this.onPropertySync) {
      const syncProp = this.onPropertySync
      element.addEventListener('timeupdate', () => {
        syncProp(refId, 'currentTime', (element as HTMLMediaElement).currentTime)
      })
      element.addEventListener('play', () => {
        syncProp(refId, 'paused', false)
      })
      element.addEventListener('pause', () => {
        syncProp(refId, 'paused', true)
      })
      element.addEventListener('loadedmetadata', () => {
        syncProp(refId, 'duration', (element as HTMLMediaElement).duration)
      })
    }

    // Attach to dialog elements
    if (element instanceof HTMLDialogElement && this.onPropertySync) {
      const syncProp = this.onPropertySync
      element.addEventListener('close', () => {
        syncProp(refId, 'open', false)
      })
    }
  }

  /**
   * Find an element by its ref ID.
   */
  findElement(refId: string): HTMLElement | null {
    return document.querySelector(`[data-pw-ref="${refId}"]`)
  }

  /**
   * Execute a command on a ref.
   */
  executeCommand(command: Command): void {
    const { cmd, refId, args = {} } = command
    const element = this.findElement(refId)

    if (!element) {
      logger.warn(`PyWire: Command '${cmd}' failed - Ref '${refId}' not found in DOM`)
      return
    }

    try {
      switch (cmd) {
        case 'focus':
          element.focus()
          break
        case 'blur':
          element.blur()
          break
        case 'reset':
          if (element instanceof HTMLFormElement) {
            element.reset()
          } else {
            logger.warn(`PyWire: 'reset' command only supported for <form> elements`)
          }
          break
        case 'submit':
          if (element instanceof HTMLFormElement) {
            element.requestSubmit()
          } else {
            logger.warn(`PyWire: 'submit' command only supported for <form> elements`)
          }
          break
        case 'scrollTo':
          element.scrollIntoView(args as ScrollIntoViewOptions)
          break
        case 'addClass':
          if (args.name) element.classList.add(args.name as string)
          break
        case 'removeClass':
          if (args.name) element.classList.remove(args.name as string)
          break
        case 'toggleClass':
          if (args.name) element.classList.toggle(args.name as string)
          break
        case 'setAttribute':
          if (args.name) element.setAttribute(args.name as string, String(args.value))
          break
        case 'removeAttribute':
          if (args.name) element.removeAttribute(args.name as string)
          break
        case 'requestRect':
          this.pendingRectRequests.add(refId)
          break
        case 'clearFileInput':
          if (element instanceof HTMLInputElement && element.type === 'file') {
            element.value = ''
          } else {
            logger.warn(
              'PyWire: \'clearFileInput\' only supported for <input type="file"> elements'
            )
          }
          break
        case 'play':
          if (element instanceof HTMLMediaElement) {
            element.play()
          } else {
            logger.warn(`PyWire: 'play' command only supported for <audio>/<video> elements`)
          }
          break
        case 'pause':
          if (element instanceof HTMLMediaElement) {
            element.pause()
          } else {
            logger.warn(`PyWire: 'pause' command only supported for <audio>/<video> elements`)
          }
          break
        case 'load':
          if (element instanceof HTMLMediaElement) {
            element.load()
          } else {
            logger.warn(`PyWire: 'load' command only supported for <audio>/<video> elements`)
          }
          break
        case 'showModal':
          if (element instanceof HTMLDialogElement) {
            element.showModal()
          } else {
            logger.warn(`PyWire: 'showModal' command only supported for <dialog> elements`)
          }
          break
        case 'close':
          if (element instanceof HTMLDialogElement) {
            element.close(args.returnValue as string)
          } else {
            logger.warn(`PyWire: 'close' command only supported for <dialog> elements`)
          }
          break
        case 'requestDataUrl':
          if (element instanceof HTMLCanvasElement) {
            const dataUrl = element.toDataURL((args.type as string) || 'image/png')
            if (this.onPropertySync) {
              const canvasRefId = element.getAttribute('data-pw-ref')
              if (canvasRefId) {
                this.onPropertySync(canvasRefId, 'dataUrl', dataUrl)
              }
            }
          } else {
            logger.warn(`PyWire: 'requestDataUrl' command only supported for <canvas> elements`)
          }
          break
        default:
          logger.warn(`PyWire: Unknown command '${cmd}'`)
      }
    } catch (e) {
      logger.error(`PyWire: Error executing command '${cmd}' on ref '${refId}':`, e)
    }
  }

  /**
   * Extract data from a ref (form or input).
   */
  getRefData(refId: string): {
    value?: ElementValue
    formData?: Record<string, FormFieldValue>
    rect?: RectData
  } {
    const element = this.findElement(refId)
    if (!element) return {}

    const data: {
      value?: ElementValue
      formData?: Record<string, FormFieldValue>
      rect?: RectData
    } = {}

    if (this.pendingRectRequests.has(refId)) {
      const rect = element.getBoundingClientRect()
      data.rect = {
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
        left: rect.left,
      }
      this.pendingRectRequests.delete(refId)
    }

    if (element instanceof HTMLFormElement) {
      data.formData = this.serializeForm(element)
    } else if (
      element instanceof HTMLInputElement ||
      element instanceof HTMLSelectElement ||
      element instanceof HTMLTextAreaElement
    ) {
      data.value = this.getElementValue(element)
    }

    return data
  }

  /**
   * Serialize a form into a JSON-friendly object.
   */
  private serializeForm(form: HTMLFormElement): Record<string, FormFieldValue> {
    const formData = new FormData(form)
    const data: Record<string, FormFieldValue> = {}

    formData.forEach((value, key) => {
      if (value instanceof File) {
        const fileMeta = {
          name: value.name,
          size: value.size,
          type: value.type,
        }
        if (key in data) {
          if (!Array.isArray(data[key])) {
            data[key] = [data[key] as FileMeta]
          }
          ;(data[key] as FileMeta[]).push(fileMeta)
        } else {
          data[key] = fileMeta
        }
        return
      }
      if (key in data) {
        if (!Array.isArray(data[key])) {
          data[key] = [data[key] as string]
        }
        ;(data[key] as string[]).push(value)
      } else {
        data[key] = value
      }
    })

    return data
  }

  /**
   * Get value from an input element.
   */
  private getElementValue(
    el: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
  ): ElementValue {
    if (el instanceof HTMLInputElement) {
      if (el.type === 'checkbox') return el.checked
      if (el.type === 'number' || el.type === 'range') return el.valueAsNumber
      if (el.type === 'file') {
        const files = Array.from(el.files ?? [])
        return files.map((file) => ({
          name: file.name,
          size: file.size,
          type: file.type,
        }))
      }
    }
    return el.value
  }
}
