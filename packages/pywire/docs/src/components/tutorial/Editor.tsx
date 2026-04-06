import React, { useEffect, useRef } from 'react'

// Monkey-patch Worker to handle the "Module scripts don't support importScripts()" error
if (typeof window !== 'undefined' && !(window as any).__workerPatched) {
  const OriginalWorker = window.Worker
  ;(window as any).Worker = function (url: string | URL, options?: WorkerOptions) {
    const urlStr = typeof url === 'string' ? url : url.toString()
    // Force classic type for all blob workers that try to be modules
    if (urlStr.startsWith('blob:') && options?.type === 'module') {
      return new OriginalWorker(url, { ...options, type: 'classic' })
    }
    return new OriginalWorker(url, options)
  } as any
  ;(window as any).__workerPatched = true
}

interface EditorProps {
  content: string
  language: string
  onChange?: (value: string) => void
  readOnly?: boolean
}

// Initialize Monaco environment for workers (once)
function setupMonacoEnvironment(_monaco: any) {
  if (typeof window === 'undefined' || (window as any).MonacoEnvironment) return
  ;(window as any).MonacoEnvironment = {
    getWorkerUrl: function (_moduleId: any, label: string) {
      const baseUrl = import.meta.env.BASE_URL.endsWith('/')
        ? import.meta.env.BASE_URL
        : `${import.meta.env.BASE_URL}/`

      const origin = window.location.origin
      const fullBaseUrl = `${origin}${baseUrl}`

      const workerUrlMap: Record<string, string> = {
        json: `${fullBaseUrl}workers/json.worker.js`,
        css: `${fullBaseUrl}workers/css.worker.js`,
        scss: `${fullBaseUrl}workers/css.worker.js`,
        less: `${fullBaseUrl}workers/css.worker.js`,
        html: `${fullBaseUrl}workers/html.worker.js`,
        handlebars: `${fullBaseUrl}workers/html.worker.js`,
        razor: `${fullBaseUrl}workers/html.worker.js`,
        typescript: `${fullBaseUrl}workers/ts.worker.js`,
        javascript: `${fullBaseUrl}workers/ts.worker.js`,
      }
      const workerUrl = workerUrlMap[label] || `${fullBaseUrl}workers/editor.worker.js`

      // Cross-origin worker wrapper using classic worker (importScripts)
      const blob = new Blob(
        [
          `self.MonacoEnvironment = { baseUrl: '${fullBaseUrl}' };
                 importScripts('${workerUrl}');`,
        ],
        { type: 'application/javascript' },
      )
      return URL.createObjectURL(blob)
    },
  }
}

// Singleton keys for global state
const GLOBAL_MONACO_KEY = '__PYWIRE_MONACO_EDITOR__'
const GLOBAL_HIGHLIGHTER_KEY = '__PYWIRE_SHIKI_HIGHLIGHTER__'
const GLOBAL_MONACO_STYLES_KEY = '__PYWIRE_MONACO_STYLES__'

// Type declarations for window
declare global {
  interface Window {
    [GLOBAL_MONACO_KEY]?: {
      editor: any
      monaco: any
      container: HTMLDivElement
      onChangeCallback?: (value: string) => void
      isInitializing?: boolean
      initPromise?: Promise<void>
    }
    [GLOBAL_HIGHLIGHTER_KEY]?: any
    [GLOBAL_MONACO_STYLES_KEY]?: string[]
  }
}

// Preserve Monaco styles before View Transition swap
function setupMonacoStylePreservation() {
  if (typeof window === 'undefined') return

  // Only set up once
  if ((window as any).__monacoStylePreservationSetup) return
  ;(window as any).__monacoStylePreservationSetup = true

  // Before swap: capture all Monaco style content
  document.addEventListener('astro:before-swap', () => {
    const monacoStyles = Array.from(document.querySelectorAll('style'))
      .filter(
        (style) =>
          style.textContent?.includes('.monaco-editor') ||
          style.textContent?.includes('.mtk') ||
          style.getAttribute('data-vite-dev-id')?.includes('monaco'),
      )
      .map((style) => style.outerHTML)

    if (monacoStyles.length > 0) {
      console.log(`[Editor] Preserving ${monacoStyles.length} Monaco style elements`)
      window[GLOBAL_MONACO_STYLES_KEY] = monacoStyles
    }
  })

  // After swap: restore Monaco styles if they were lost
  document.addEventListener('astro:after-swap', () => {
    const savedStyles = window[GLOBAL_MONACO_STYLES_KEY]
    if (!savedStyles || savedStyles.length === 0) return

    // Check if Monaco styles are still present
    const currentMonacoStyles = Array.from(document.querySelectorAll('style')).filter((style) =>
      style.textContent?.includes('.monaco-editor'),
    )

    if (currentMonacoStyles.length === 0) {
      console.log(`[Editor] Restoring ${savedStyles.length} Monaco style elements`)

      // Create a container to parse the saved HTML
      const container = document.createElement('div')
      savedStyles.forEach((styleHtml) => {
        container.innerHTML = styleHtml
        const style = container.firstChild as HTMLStyleElement
        if (style) {
          document.head.appendChild(style)
        }
      })
    }

    // Trigger layout refresh on the editor if it exists
    const globalEditor = window[GLOBAL_MONACO_KEY]
    if (globalEditor?.editor) {
      setTimeout(() => {
        globalEditor.editor.layout()
      }, 0)
    }
  })
}

// Initialize style preservation on module load
if (typeof window !== 'undefined') {
  setupMonacoStylePreservation()
}

export const Editor: React.FC<EditorProps> = ({
  content,
  language,
  onChange,
  readOnly = false,
}) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const onChangeRef = useRef(onChange)

  useEffect(() => {
    onChangeRef.current = onChange
  }, [onChange])

  useEffect(() => {
    let observer: MutationObserver | null = null

    async function init() {
      if (!containerRef.current) return

      // Check if we have a persisted editor instance
      const globalEditor = window[GLOBAL_MONACO_KEY]

      if (globalEditor?.editor && globalEditor.container) {
        console.log('[Editor] Reusing existing Monaco editor instance')

        // Move the persisted container into our ref
        if (containerRef.current && globalEditor.container.parentNode !== containerRef.current) {
          containerRef.current.appendChild(globalEditor.container)
        }

        // Update the onChange callback
        globalEditor.onChangeCallback = (value: string) => onChangeRef.current?.(value)

        // Update content if different
        if (globalEditor.editor.getValue() !== content) {
          globalEditor.editor.setValue(content)
        }

        // Update readOnly
        globalEditor.editor.updateOptions({ readOnly })

        // Trigger layout refresh
        setTimeout(() => globalEditor.editor.layout(), 0)

        return
      }

      // If initialization is in progress, wait for it
      if (globalEditor?.isInitializing && globalEditor.initPromise) {
        await globalEditor.initPromise
        // Retry after init completes
        init()
        return
      }

      console.log('[Editor] Creating new Monaco editor instance')

      // Create a persistent container that survives navigation
      const persistentContainer = document.createElement('div')
      persistentContainer.style.height = '100%'
      persistentContainer.style.width = '100%'
      persistentContainer.id = 'pw-monaco-editor-container'
      containerRef.current.appendChild(persistentContainer)

      // Mark as initializing
      window[GLOBAL_MONACO_KEY] = {
        editor: null,
        monaco: null,
        container: persistentContainer,
        isInitializing: true,
      }

      const initPromise = (async () => {
        // Dynamically import monaco-editor and shiki to avoid SSR issues
        const [monaco, { createHighlighter }, { shikiToMonaco }] = await Promise.all([
          import('monaco-editor'),
          import('shiki'),
          import('@shikijs/monaco'),
        ])

        // Register PyWire language in Monaco if not already done
        if (!monaco.languages.getLanguages().some((lang) => lang.id === 'pywire')) {
          monaco.languages.register({
            id: 'pywire',
            extensions: ['.wire'],
            aliases: ['PyWire', 'pywire'],
          })
        }

        // Initialize Shiki if not already done
        if (!window[GLOBAL_HIGHLIGHTER_KEY]) {
          const baseUrl = (import.meta.env.BASE_URL || '/').endsWith('/')
            ? import.meta.env.BASE_URL || '/'
            : `${import.meta.env.BASE_URL}/`

          const fullBaseUrl = `${window.location.origin}${baseUrl}`
          const grammarUrl = `${fullBaseUrl}grammars/pywire.tmLanguage.json`

          let pywireGrammar = null
          try {
            const response = await fetch(grammarUrl)
            if (response.ok) {
              pywireGrammar = await response.json()
            }
          } catch (e) {
            console.error('Error fetching PyWire grammar:', e)
          }

          const langs: any[] = ['python', 'html', 'css', 'javascript', 'json', 'typescript']
          if (pywireGrammar) {
            langs.push({
              ...pywireGrammar,
              name: 'pywire',
            })
          }

          const [mochaTheme, latteTheme] = await Promise.all([
            import('shiki/themes/catppuccin-mocha.mjs'),
            import('shiki/themes/catppuccin-latte.mjs'),
          ])

          const highlighter = await createHighlighter({
            themes: [mochaTheme.default, latteTheme.default],
            langs: langs,
          })

          shikiToMonaco(highlighter, monaco)
          window[GLOBAL_HIGHLIGHTER_KEY] = highlighter
        }

        setupMonacoEnvironment(monaco)

        const isDark = document.documentElement.getAttribute('data-theme') !== 'light'
        const theme = isDark ? 'catppuccin-mocha' : 'catppuccin-latte'
        const monacoLanguage = language === 'pywire' ? 'pywire' : language

        const editor = monaco.editor.create(persistentContainer, {
          value: content,
          language: monacoLanguage,
          theme: theme,
          automaticLayout: true,
          minimap: { enabled: false },
          fontSize: 14,
          lineNumbers: 'on',
          scrollBeyondLastLine: false,
          roundedSelection: false,
          padding: { top: 10 },
          readOnly: readOnly,
        })

        // Update global state
        window[GLOBAL_MONACO_KEY] = {
          editor,
          monaco,
          container: persistentContainer,
          onChangeCallback: (value: string) => onChangeRef.current?.(value),
          isInitializing: false,
        }

        editor.onDidChangeModelContent(() => {
          window[GLOBAL_MONACO_KEY]?.onChangeCallback?.(editor.getValue())
        })

        // Watch for theme changes from Starlight
        observer = new MutationObserver((mutations) => {
          mutations.forEach((_mutation) => {
            const newTheme = document.documentElement.getAttribute('data-theme')
            monaco.editor.setTheme(newTheme === 'light' ? 'catppuccin-latte' : 'catppuccin-mocha')
          })
        })

        observer.observe(document.documentElement, {
          attributes: true,
          attributeFilter: ['data-theme'],
        })
      })()

      window[GLOBAL_MONACO_KEY]!.initPromise = initPromise
      await initPromise
    }

    init()

    return () => {
      // Don't dispose the editor - let it persist for navigation
      // Just disconnect the observer if we created one locally
      if (observer) observer.disconnect()
    }
  }, []) // Empty deps - only run once per mount

  // Update content when props change
  useEffect(() => {
    const globalEditor = window[GLOBAL_MONACO_KEY]
    if (globalEditor?.editor) {
      if (globalEditor.editor.getValue() !== content) {
        globalEditor.editor.setValue(content)
      }
      globalEditor.editor.updateOptions({ readOnly })
      // Update the callback reference
      globalEditor.onChangeCallback = (value: string) => onChangeRef.current?.(value)
    }
  }, [content, readOnly])

  return <div ref={containerRef} style={{ height: '100%', width: '100%' }} />
}
