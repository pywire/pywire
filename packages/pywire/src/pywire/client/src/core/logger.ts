/**
 * Simple client-side logger that respects debug flag.
 */
export class Logger {
  constructor(private debug: boolean = false) {}

  log(...args: unknown[]): void {
    if (this.debug) {
      console.log(...args)
    }
  }

  warn(...args: unknown[]): void {
    if (this.debug) {
      console.warn(...args)
    }
  }

  error(...args: unknown[]): void {
    // Errors are always logged
    console.error(...args)
  }

  info(...args: unknown[]): void {
    if (this.debug) {
      console.info(...args)
    }
  }

  setDebug(debug: boolean): void {
    this.debug = debug
  }
}

export const logger = new Logger()
