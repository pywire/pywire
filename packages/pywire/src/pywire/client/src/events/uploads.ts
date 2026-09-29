/**
 * File inputs in pywire forms upload as soon as files are picked.
 *
 * The files go to `/_pywire/upload` with the page's upload token, and a
 * submit carries only their ids, waiting for any upload still running.
 * While an input uploads it carries `data-pw-uploading` and `aria-busy`, and
 * every `<progress data-pw-progress-for="<input id>">` shows how far it got.
 * Picking again cancels the running upload.
 *
 * Before anything is sent, the picked files are checked against the
 * input's `accept`, `data-pw-max-size` and `data-pw-max-files` (rendered
 * from `UploadField`); the server checks them again on submit.
 */

/** A staged file, with the token it was uploaded with: the server resolves
 * an id only alongside the token of the page that uploaded it. */
export type UploadRef = { _upload_id: string; _upload_token: string }

/**
 * How long an upload is reused. The server keeps staged files for an hour;
 * past this, a submit uploads the file again rather than send an id that may
 * have expired.
 */
export const REUSE_MS = 30 * 60 * 1000

type Entry = {
  files: File[]
  xhr: XMLHttpRequest
  ids: Promise<UploadRef[]>
  done: UploadRef[] | null
  at: number
}

const UPLOADING = 'data-pw-uploading'

/** Bytes for people, the way the server says them (`format_size`). */
export function formatSize(size: number): string {
  const binary: Array<[string, number]> = [
    ['GiB', 1024 ** 3],
    ['MiB', 1024 ** 2],
    ['KiB', 1024],
  ]
  for (const [unit, factor] of binary) {
    if (size >= factor && size % factor === 0) return `${size / factor} ${unit}`
  }
  const decimal: Array<[string, number]> = [
    ['GB', 1000 ** 3],
    ['MB', 1000 ** 2],
    ['KB', 1000],
  ]
  for (const [unit, factor] of decimal) {
    if (size >= factor) return `${(size / factor).toFixed(1).replace(/\.0$/, '')} ${unit}`
  }
  return `${size} B`
}

function accepts(tokens: string[], file: File): boolean {
  if (!tokens.length) return true
  const name = file.name.toLowerCase()
  const type = file.type.split(';')[0].trim().toLowerCase()
  return tokens.some((token) => {
    if (token.startsWith('.')) return name.endsWith(token)
    if (token.endsWith('/*')) return type.startsWith(token.slice(0, -1))
    return type === token
  })
}

/** Why these files can't be sent from this input, or null. */
export function checkFiles(input: HTMLInputElement, files: File[]): string | null {
  // A `novalidate` form shows its own messages: the file goes up and the
  // server's check puts the message where the page shows field errors.
  if (input.form?.noValidate) return null
  const maxFiles = Number.parseInt(input.dataset.pwMaxFiles ?? '', 10)
  if (maxFiles > 0 && files.length > maxFiles) {
    return `Choose at most ${maxFiles} files`
  }
  const maxSize = Number.parseInt(input.dataset.pwMaxSize ?? '', 10)
  const tokens = input.accept
    .split(',')
    .map((t) => t.trim().toLowerCase())
    .filter((t) => t)
  for (const file of files) {
    if (maxSize >= 0 && file.size > maxSize) {
      return `Choose a file no larger than ${formatSize(maxSize)}`
    }
    if (!accepts(tokens, file)) return `Choose a file of type ${tokens.join(', ')}`
  }
  return null
}

function sameFiles(a: File[], b: File[]): boolean {
  return a.length === b.length && a.every((file, i) => file === b[i])
}

function progressBars(input: HTMLInputElement): HTMLProgressElement[] {
  if (!input.id) return []
  return Array.from(
    document.querySelectorAll<HTMLProgressElement>('progress[data-pw-progress-for]')
  ).filter((bar) => bar.dataset.pwProgressFor === input.id)
}

function showProgress(input: HTMLInputElement, fraction: number | null): void {
  const busy = fraction !== null
  input.toggleAttribute(UPLOADING, busy)
  if (busy) input.setAttribute('aria-busy', 'true')
  else input.removeAttribute('aria-busy')
  for (const bar of progressBars(input)) {
    bar.toggleAttribute(UPLOADING, busy)
    bar.max = 1
    bar.value = fraction ?? 1
  }
}

/** Attributes a morph must leave on a file input while it uploads. */
export function isUploadState(input: HTMLInputElement, attr: string): boolean {
  return input.hasAttribute(UPLOADING) && (attr === UPLOADING || attr === 'aria-busy')
}

/** A morph keeps an upload progress bar as the client last drew it. */
export function keepUploadProgress(from: HTMLProgressElement, to: HTMLProgressElement): void {
  if (!from.dataset.pwProgressFor || from.dataset.pwProgressFor !== to.dataset.pwProgressFor) {
    return
  }
  to.max = from.max
  to.value = from.value
  to.toggleAttribute(UPLOADING, from.hasAttribute(UPLOADING))
}

export class UploadError extends Error {}

export class Uploader {
  private entries = new WeakMap<HTMLInputElement, Entry>()

  constructor(
    private url: () => string,
    private onUploaded: (input: HTMLInputElement) => void
  ) {}

  /** The user picked files: check them, then start uploading. */
  select(input: HTMLInputElement): void {
    this.cancel(input)
    input.setCustomValidity('')
    const files = Array.from(input.files ?? [])
    if (!files.length) return
    const problem = checkFiles(input, files)
    if (problem) {
      input.setCustomValidity(problem)
      input.reportValidity()
      return
    }
    // A failure is reported on the input; the submit retries.
    this.start(input, files).catch(() => undefined)
  }

  /** References to the files the input holds now, uploading them if needed. */
  async ids(input: HTMLInputElement): Promise<UploadRef[]> {
    const files = Array.from(input.files ?? [])
    if (!files.length) return []
    const entry = this.fresh(input, files)
    if (entry) return entry.ids
    const problem = checkFiles(input, files)
    if (problem) throw new UploadError(problem)
    return this.start(input, files)
  }

  /** References to the input's files once uploaded; none while uploading. */
  uploaded(input: HTMLInputElement): UploadRef[] {
    return this.fresh(input, Array.from(input.files ?? []))?.done ?? []
  }

  /** The upload of exactly these files, unless it is old enough to expire. */
  private fresh(input: HTMLInputElement, files: File[]): Entry | undefined {
    const entry = this.entries.get(input)
    if (!entry || !sameFiles(entry.files, files)) return undefined
    if (entry.done && Date.now() - entry.at > REUSE_MS) {
      this.entries.delete(input)
      return undefined
    }
    return entry
  }

  cancel(input: HTMLInputElement): void {
    const entry = this.entries.get(input)
    if (!entry) return
    this.entries.delete(input)
    if (!entry.done) {
      entry.xhr.abort()
      showProgress(input, null)
    }
  }

  private start(input: HTMLInputElement, files: File[]): Promise<UploadRef[]> {
    const token = document.querySelector<HTMLMetaElement>(
      'meta[name="pywire-upload-token"]'
    )?.content
    if (!token) {
      return Promise.reject(
        new UploadError('Missing upload token. File uploads are not enabled for this page.')
      )
    }
    const body = new FormData()
    for (const file of files) body.append(input.name, file)
    const xhr = new XMLHttpRequest()
    const entry: Entry = { files, xhr, ids: Promise.resolve([]), done: null, at: Date.now() }

    const fail = (message: string): UploadError => {
      if (this.entries.get(input) === entry) this.entries.delete(input)
      showProgress(input, null)
      input.setCustomValidity(message)
      input.reportValidity()
      return new UploadError(message)
    }

    entry.ids = new Promise<UploadRef[]>((resolve, reject) => {
      xhr.open('POST', this.url())
      xhr.setRequestHeader('X-Upload-Token', token)
      const session = (window as Window & { __PYWIRE_HTTP_SESSION?: string | null })
        .__PYWIRE_HTTP_SESSION
      if (typeof session === 'string' && session) {
        xhr.setRequestHeader('X-PyWire-Session', session)
      }
      xhr.upload.onprogress = (e: ProgressEvent) => {
        if (e.lengthComputable && e.total > 0) showProgress(input, e.loaded / e.total)
      }
      xhr.onload = () => {
        let payload: Record<string, unknown> = {}
        try {
          payload = JSON.parse(xhr.responseText) as Record<string, unknown>
        } catch {
          /* not JSON: reported below */
        }
        const ids = payload[input.name]
        if (xhr.status < 200 || xhr.status >= 300 || !Array.isArray(ids)) {
          reject(
            fail(
              xhr.status === 413
                ? 'This file is too large to upload'
                : String(payload.error ?? 'Upload failed')
            )
          )
          return
        }
        entry.done = ids.map((id) => ({ _upload_id: String(id), _upload_token: token }))
        entry.at = Date.now()
        showProgress(input, null)
        for (const bar of progressBars(input)) bar.value = 1
        resolve(entry.done)
        this.onUploaded(input)
      }
      xhr.onerror = () => reject(fail('Upload failed'))
      xhr.onabort = () => reject(new UploadError('Upload cancelled'))
      xhr.send(body)
    })
    this.entries.set(input, entry)
    showProgress(input, 0)
    return entry.ids
  }
}
