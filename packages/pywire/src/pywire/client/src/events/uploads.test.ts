import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { UnifiedEventHandler } from './handler'
import { releaseForms } from './forms'
import { checkFiles, formatSize, keepUploadProgress, REUSE_MS } from './uploads'
import { PyWireApp } from '../core/app'

class FakeXHR {
  static all: FakeXHR[] = []
  url = ''
  headers: Record<string, string> = {}
  body: FormData | null = null
  status = 0
  responseText = ''
  aborted = false
  upload: { onprogress: ((e: ProgressEvent) => void) | null } = { onprogress: null }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  onabort: (() => void) | null = null

  constructor() {
    FakeXHR.all.push(this)
  }
  open(_method: string, url: string): void {
    this.url = url
  }
  setRequestHeader(key: string, value: string): void {
    this.headers[key] = value
  }
  send(body: FormData): void {
    this.body = body
  }
  abort(): void {
    this.aborted = true
    this.onabort?.()
  }
  progress(loaded: number, total: number): void {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total } as ProgressEvent)
  }
  respond(status: number, payload: unknown): void {
    this.status = status
    this.responseText = JSON.stringify(payload)
    this.onload?.()
  }
}

const FORM = `
  <meta name="pywire-upload-token" content="tok">
  <form id="f" data-pw-form="f" data-pw-validate="blur" data-on-submit="_handler_0">
    <input id="name" name="name" value="Al">
    <input id="avatar" name="avatar" type="file" accept="image/*" data-pw-max-size="1000">
    <input id="docs" name="docs" type="file" multiple data-pw-max-files="2">
    <progress data-pw-progress-for="avatar" max="1" value="0"></progress>
  </form>`

const png = (size = 10, name = 'a.png'): File =>
  new File(['x'.repeat(size)], name, { type: 'image/png' })

describe('uploads', () => {
  // One handler for the whole file: document listeners outlive a test.
  const app: {
    sendEvent: ReturnType<typeof vi.fn>
    getConfig: ReturnType<typeof vi.fn>
    mountPath: string
    isInteractive?: boolean
  } = { sendEvent: vi.fn(), getConfig: vi.fn().mockReturnValue({}), mountPath: '/app' }
  const handler = new UnifiedEventHandler(app as unknown as PyWireApp)
  handler.init()

  const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T
  const pick = (id: string, files: File[]): void => {
    const input = $<HTMLInputElement>(id)
    Object.defineProperty(input, 'files', { value: files, configurable: true })
    input.dispatchEvent(new Event('change', { bubbles: true }))
  }
  const submit = (): void => {
    $('f').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  }
  const flush = async (): Promise<void> => {
    for (let i = 0; i < 5; i++) await Promise.resolve()
  }
  const sent = (): Array<[string, Record<string, unknown>]> =>
    app.sendEvent.mock.calls as Array<[string, Record<string, unknown>]>

  beforeEach(() => {
    FakeXHR.all = []
    vi.stubGlobal('XMLHttpRequest', FakeXHR)
    document.body.innerHTML = FORM
    app.sendEvent.mockReset()
    app.isInteractive = undefined
  })

  afterEach(() => {
    releaseForms()
    vi.unstubAllGlobals()
  })

  it('uploads a file when it is picked, with progress', async () => {
    pick('avatar', [png()])
    expect(FakeXHR.all).toHaveLength(1)
    const xhr = FakeXHR.all[0]
    expect(xhr.url).toBe('/app/_pywire/upload')
    expect(xhr.headers['X-Upload-Token']).toBe('tok')
    expect(xhr.body?.getAll('avatar')).toHaveLength(1)

    const input = $<HTMLInputElement>('avatar')
    const bar = document.querySelector('progress') as HTMLProgressElement
    expect(input.hasAttribute('data-pw-uploading')).toBe(true)
    xhr.progress(5, 10)
    expect(bar.value).toBe(0.5)
    expect(bar.hasAttribute('data-pw-uploading')).toBe(true)

    xhr.respond(200, { avatar: ['id1'] })
    await flush()
    expect(input.hasAttribute('data-pw-uploading')).toBe(false)
    expect(bar.value).toBe(1)
    // A live form checks the field once its file is up.
    expect(sent()).toHaveLength(1)
    expect(sent()[0][1]).toMatchObject({
      type: 'validate',
      field: 'avatar',
      formData: { name: 'Al', avatar: { _upload_id: 'id1', _upload_token: 'tok' } },
    })
  })

  it('submits upload ids, waiting for uploads still running', async () => {
    pick('avatar', [png()])
    pick('docs', [png(1, 'one.png'), png(1, 'two.png')])
    submit()
    await flush()
    expect(app.sendEvent).not.toHaveBeenCalled()

    FakeXHR.all[0].respond(200, { avatar: ['a1'] })
    FakeXHR.all[1].respond(200, { docs: ['d1', 'd2'] })
    await flush()
    const submits = sent().filter(([, data]) => data.type === 'submit')
    expect(submits).toHaveLength(1)
    expect(submits[0][1].formData).toEqual({
      name: 'Al',
      avatar: { _upload_id: 'a1', _upload_token: 'tok' },
      docs: [
        { _upload_id: 'd1', _upload_token: 'tok' },
        { _upload_id: 'd2', _upload_token: 'tok' },
      ],
    })
    expect(FakeXHR.all).toHaveLength(2) // nothing uploaded twice
  })

  it('uploads again rather than send an id that may have expired', async () => {
    const now = Date.now()
    const clock = vi.spyOn(Date, 'now').mockReturnValue(now)
    pick('avatar', [png()])
    FakeXHR.all[0].respond(200, { avatar: ['old'] })
    await flush()

    clock.mockReturnValue(now + REUSE_MS + 1)
    submit()
    await flush()
    expect(FakeXHR.all).toHaveLength(2)
    FakeXHR.all[1].respond(200, { avatar: ['new'] })
    await flush()
    const submits = sent().filter(([, data]) => data.type === 'submit')
    expect((submits[0][1].formData as Record<string, unknown>).avatar).toEqual({
      _upload_id: 'new',
      _upload_token: 'tok',
    })
    clock.mockRestore()
  })

  it('picking again cancels the running upload', () => {
    pick('avatar', [png()])
    pick('avatar', [png(20)])
    expect(FakeXHR.all).toHaveLength(2)
    expect(FakeXHR.all[0].aborted).toBe(true)
    expect(FakeXHR.all[1].aborted).toBe(false)
  })

  it('checks files before uploading them', () => {
    const avatar = $<HTMLInputElement>('avatar')
    const report = vi.spyOn(avatar, 'reportValidity').mockReturnValue(false)
    pick('avatar', [png(2000)])
    expect(FakeXHR.all).toHaveLength(0)
    expect(avatar.validationMessage).toBe('Choose a file no larger than 1 KB')
    expect(report).toHaveBeenCalled()

    pick('avatar', [new File(['x'], 'a.txt', { type: 'text/plain' })])
    expect(avatar.validationMessage).toBe('Choose a file of type image/*')

    pick('avatar', [png()])
    expect(avatar.validationMessage).toBe('')
    expect(FakeXHR.all).toHaveLength(1)
  })

  it('reports a failed upload on the input and releases the form', async () => {
    const avatar = $<HTMLInputElement>('avatar')
    vi.spyOn(avatar, 'reportValidity').mockReturnValue(false)
    pick('avatar', [png()])
    submit()
    FakeXHR.all[0].respond(413, { error: 'Payload Too Large' })
    await flush()
    expect(avatar.validationMessage).toBe('This file is too large to upload')
    expect($('f').hasAttribute('data-pw-submitting')).toBe(false)
    expect(sent().filter(([, data]) => data.type === 'submit')).toHaveLength(0)
  })

  it('leaves file inputs to the form post when not interactive', () => {
    app.isInteractive = false
    pick('avatar', [png()])
    expect(FakeXHR.all).toHaveLength(0)
  })
})

describe('checkFiles', () => {
  const input = (attrs: string): HTMLInputElement => {
    document.body.innerHTML = `<input type="file" ${attrs}>`
    return document.querySelector('input') as HTMLInputElement
  }

  it('matches accept the way the browser does', () => {
    const el = input('accept=".PDF, image/*"')
    expect(checkFiles(el, [new File(['x'], 'A.pdf')])).toBeNull()
    expect(checkFiles(el, [new File(['x'], 'a.jpg', { type: 'image/jpeg' })])).toBeNull()
    expect(checkFiles(el, [new File(['x'], 'a.doc', { type: 'text/x' })])).toBe(
      'Choose a file of type .pdf, image/*'
    )
  })

  it('counts files', () => {
    const el = input('multiple data-pw-max-files="2"')
    const file = new File(['x'], 'a')
    expect(checkFiles(el, [file, file])).toBeNull()
    expect(checkFiles(el, [file, file, file])).toBe('Choose at most 2 files')
  })
})

describe('formatSize', () => {
  it('says sizes the way the server does', () => {
    expect(formatSize(500)).toBe('500 B')
    expect(formatSize(2_000_000)).toBe('2 MB')
    expect(formatSize(2_100_000)).toBe('2.1 MB')
    expect(formatSize(2 * 1024 * 1024)).toBe('2 MiB')
    expect(formatSize(1536)).toBe('1.5 KB')
  })
})

describe('keepUploadProgress', () => {
  it('keeps what the client drew on a bar tied to an input', () => {
    document.body.innerHTML = `
      <progress id="a" data-pw-progress-for="x" data-pw-uploading max="1" value="0.4"></progress>
      <progress id="b" data-pw-progress-for="x" max="1" value="0"></progress>
      <progress id="c" max="1" value="0"></progress>`
    const [a, b, c] = ['a', 'b', 'c'].map(
      (id) => document.getElementById(id) as HTMLProgressElement
    )
    keepUploadProgress(a, b)
    expect(b.value).toBeCloseTo(0.4)
    expect(b.hasAttribute('data-pw-uploading')).toBe(true)
    keepUploadProgress(a, c)
    expect(c.value).toBe(0)
  })
})
