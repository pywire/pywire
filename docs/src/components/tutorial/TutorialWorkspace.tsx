import React, { useState, useEffect, useRef, useCallback } from 'react'
import { Panel, Group, Separator } from 'react-resizable-panels'
import { Editor } from './Editor'
import { BrowserPreview } from './BrowserPreview'
import { TutorialFileTree } from './tree/TutorialFileTree'
import { LoadingSpinner } from './LoadingSpinner'
import { TutorialEngine } from './TutorialEngine'
import { TutorialHierarchy } from './TutorialHierarchy'
import { useTutorialStorage } from '../../hooks/useTutorialStorage'
import { Menu, ArrowLeft, ArrowRight, CheckCircle, RotateCcw } from 'lucide-react'
import type { TutorialStep } from './types'
import { MarkdownRenderer } from './MarkdownRenderer'
import { Modal } from './Modal'
import { SuccessValidator, type ValidationResult } from './SuccessValidator'
import { TasksChecklist } from './TasksChecklist'

import '../../styles/pywire-tutorial.css'

interface TutorialWorkspaceProps extends React.PropsWithChildren {
  initialSlug: string
  allSteps: TutorialStep[]
}

export const TutorialWorkspace: React.FC<TutorialWorkspaceProps> = ({ initialSlug, allSteps }) => {
  // console.log('[TutorialWorkspace] Render', { initialSlug, stepsCount: allSteps.length });
  const isFirstRender = useRef(true)
  useEffect(() => {
    if (!isFirstRender.current) {
      console.log('[TutorialWorkspace] PERSISTED - Props updated to:', initialSlug)
    }
    isFirstRender.current = false
    if (initialSlug) {
      localStorage.setItem('tutorial-current-slug', initialSlug)
    }
  }, [initialSlug])

  // SPA Routing State -> Now Driven by Props + Persistence
  const [currentSlug, setCurrentSlug] = useState(initialSlug)

  // Sync state with props when View Transitions navigate
  useEffect(() => {
    if (initialSlug !== currentSlug) {
      setCurrentSlug(initialSlug)
    }
  }, [initialSlug])

  // Derived State
  const currentIndex = allSteps.findIndex((s) => s.slug === currentSlug)
  const currentStep = allSteps[currentIndex !== -1 ? currentIndex : 0]
  const nextStep = currentIndex < allSteps.length - 1 ? allSteps[currentIndex + 1] : undefined
  const prevStep = currentIndex > 0 ? allSteps[currentIndex - 1] : undefined

  // Safety check if slug is invalid
  if (currentIndex === -1 && allSteps.length > 0) {
    console.warn(`Invalid slug ${currentSlug}, falling back to first step`)
  }

  // Persistence: engineRef stays alive across props changes because the component stays mounted
  const engineRef = useRef<TutorialEngine | null>(null)
  const [isReady, setIsReady] = useState(false)
  const [loadingMessage, setLoadingMessage] = useState('Initializing Pyodide...')
  const [theme, setTheme] = useState<'light' | 'dark'>('dark')
  // Browser URL State
  const [currentUrl, setCurrentUrl] = useState(currentStep.initialRoute || '/')

  // Code state - using step-specific storage for MULTIPLE files
  const { files, updateFile, addFile, deleteFile, resetFiles, resetAll, solveFiles } =
    useTutorialStorage(currentStep.slug, currentStep.files)

  const [activeFile, setActiveFile] = useState(currentStep.files[0]?.path || 'index.wire')
  const code = files[activeFile] || ''
  const debouncedFiles = useDebounce(files, 600)

  // Validation State
  const [isCompleted, setIsCompleted] = useState(false)
  const [lastRenderedHtml, setLastRenderedHtml] = useState('')
  const [validationResults, setValidationResults] = useState<ValidationResult[]>([])

  // Modal States
  const [modal, setModal] = useState<{
    isOpen: boolean
    title?: string
    message: string
    allowedItems?: string[]
  }>({ isOpen: false, message: '' })

  const [resetConfirmModal, setResetConfirmModal] = useState(false)

  const [inputModal, setInputModal] = useState<{
    isOpen: boolean
    folderPath: string
    isFolder: boolean
  } | null>(null)
  const [inputName, setInputName] = useState('')

  const [hierarchyOpen, setHierarchyOpen] = useState(false)

  const handleResetClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.metaKey || e.ctrlKey) {
        setResetConfirmModal(true)
      } else {
        resetFiles()
      }
    },
    [resetFiles],
  )

  // Handle History (Browser Back/Forward)
  // ... (lines 50-70 unchanged)
  // URL Generation Helper
  const getStepUrl = useCallback((slug: string) => {
    const baseUrl = import.meta.env.BASE_URL.replace(/\/$/, '')
    return `${baseUrl}/tutorial/${slug}/`
  }, [])

  // Parent-side history stack for the in-iframe browser. The iframe is
  // same-origin and shares the joint session history with the host
  // window, so calling `iframe.contentWindow.history.back()` can leak
  // past the iframe and navigate the docs page itself. We track URLs
  // here instead and never touch iframe.history.
  const [urlStack, setUrlStack] = useState<string[]>([currentStep.initialRoute || '/'])
  const [urlCursor, setUrlCursor] = useState(0)

  const handleNavigate = useCallback(
    (path: string) => {
      setCurrentUrl(path)
      setUrlStack((prev) => {
        const truncated = prev.slice(0, urlCursor + 1)
        if (truncated[truncated.length - 1] === path) return truncated
        const next = [...truncated, path]
        setUrlCursor(next.length - 1)
        return next
      })
      engineRef.current?.httpRequest('GET', path)
    },
    [engineRef.current, urlCursor],
  )

  const handleBack = useCallback(() => {
    if (urlCursor <= 0) return
    const next = urlCursor - 1
    setUrlCursor(next)
    setCurrentUrl(urlStack[next])
    engineRef.current?.httpRequest('GET', urlStack[next])
  }, [urlCursor, urlStack])

  const handleForward = useCallback(() => {
    if (urlCursor >= urlStack.length - 1) return
    const next = urlCursor + 1
    setUrlCursor(next)
    setCurrentUrl(urlStack[next])
    engineRef.current?.httpRequest('GET', urlStack[next])
  }, [urlCursor, urlStack])

  const handlePreviewMessage = useCallback(
    (msg: any) => {
      if (!engineRef.current) return
      switch (msg.type) {
        case 'WS_CONNECT':
          engineRef.current.wsConnect(msg.payload.path)
          break
        case 'WS_SEND':
          engineRef.current.wsSend(msg.payload.data)
          break
        case 'WS_DISCONNECT':
          engineRef.current.wsDisconnect()
          break
        case 'HTTP_REQUEST':
          engineRef.current.httpRequest(msg.payload.method, msg.payload.path, msg.payload.headers)
          break
        case 'NAVIGATE':
          handleNavigate(msg.payload.path)
          break
      }
    },
    [engineRef.current, handleNavigate],
  )

  const handleFileAddRequest = useCallback((folderPath: string, isFolder: boolean = false) => {
    setInputName('')
    setInputModal({ isOpen: true, folderPath, isFolder })
  }, [])

  const handleFileAddSubmit = useCallback(() => {
    if (!inputModal) return
    const { folderPath, isFolder } = inputModal
    const name = inputName.trim()
    if (!name) return

    // Simple validation
    if (name.includes('/') || name.includes('\\')) {
      alert('Name cannot contain slashes.')
      return
    }

    const fullPath = folderPath ? `${folderPath}/${name}` : name

    // Check behaviors
    const allowedPatterns = Object.keys(currentStep.behaviors?.canAddFiles || {})
    const isAllowed = allowedPatterns.some((p) => {
      if (isFolder) {
        return p.startsWith(fullPath + '/')
      } else {
        const regex = new RegExp('^' + p.replace(/\*/g, '.*') + '$')
        return regex.test(fullPath)
      }
    })

    if (!isAllowed && allowedPatterns.length > 0) {
      setModal({
        isOpen: true,
        message: `Only specific files and folders are allowed in this exercise:`,
        allowedItems: allowedPatterns,
      })
      return
    }

    if (isFolder) {
      addFile(`${fullPath}/.keep`, '')
    } else {
      addFile(fullPath, '')
      setActiveFile(fullPath)
    }
    setInputModal(null)
  }, [inputModal, inputName, currentStep.behaviors, addFile])

  const handleFileDelete = useCallback(
    (path: string) => {
      if (window.confirm(`Are you sure you want to delete ${path}?`)) {
        deleteFile(path)
        if (activeFile === path) {
          setActiveFile(Object.keys(files).find((f) => f !== path) || '')
        }
      }
    },
    [deleteFile, activeFile, files],
  )

  // Initialize engine once (singleton persists across navigation)
  useEffect(() => {
    console.log('[TutorialWorkspace] Engine Init Effect')
    // Register Service Worker
    if ('serviceWorker' in navigator) {
      const baseUrl = import.meta.env.BASE_URL.replace(/\/$/, '')
      navigator.serviceWorker
        .register(`${baseUrl}/sw.js`)
        .then((reg) => console.log('[Tutorial] Service Worker registered:', reg.scope))
        .catch((err) => console.warn('[Tutorial] Service Worker registration failed:', err))
    }

    // Use getInstance to get/create the global singleton engine
    console.log('[TutorialWorkspace] Getting TutorialEngine singleton')
    engineRef.current = TutorialEngine.getInstance({
      onReady: () => {
        console.log('[TutorialWorkspace] Engine Ready')
        setIsReady(true)
      },
      onResponse: (data) => {
        if (data.type === 'http_response' && data.message.type === 'http.response.body') {
          const body = data.message.body
          const html = Array.isArray(body) ? new TextDecoder().decode(new Uint8Array(body)) : body
          setLastRenderedHtml(html)
          // We're about to rewrite the iframe document — explicitly tear
          // down the prior server-side WS so its forwarder + ping_loop
          // don't outlive the iframe doc that owned them. Belt and
          // suspenders: the iframe's MockWebSocket.close() also fires
          // WS_DISCONNECT during PyWireApp.disconnect(), but that path
          // depends on the prior PyWireCore actually being live on the
          // iframe window at this moment, which it isn't always (e.g.
          // first paint, or if the prior init hadn't finished loading).
          engineRef.current?.wsDisconnect?.()
          // HTTP response means a fresh version of the app (e.g. code change)
          // We must use INIT to create a fresh document and WebSocket connection
          ;(window as any).__PYWIRE_INIT_PREVIEW__?.(html)
        } else if (data.type === 'ws_message') {
          // Forward all WebSocket messages to the preview
          // This allows the PyWire client inside the iframe to handle its own updates
          ;(window as any).__PYWIRE_SEND_TO_PREVIEW__?.(data)
        }
      },
      onLog: (msg) => {
        console.log('[TutorialWorkspace] Engine Log:', msg)
        if (!isReady) {
          const cleanMsg = msg.replace(/\u001b\[\d+m/g, '')
          setLoadingMessage(cleanMsg)
        }
      },
    })

    // If engine is already ready (from previous mount), setIsReady will be called by updateCallbacks

    // Handle theme sync with Starlight/system
    const initialTheme =
      document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark'
    setTheme(initialTheme)

    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (mutation.type === 'attributes' && mutation.attributeName === 'data-theme') {
          setTheme(
            document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark',
          )
        }
      })
    })
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    })

    return () => observer.disconnect()
  }, [])

  // ... (rest of derived state)

  // Update currentUrl when step changes; also reset the in-iframe browser's
  // history stack so back/forward don't carry across tutorials.
  useEffect(() => {
    const initial = currentStep.initialRoute || '/'
    setCurrentUrl(initial)
    setUrlStack([initial])
    setUrlCursor(0)
  }, [currentStep.slug, currentStep.initialRoute])

  // Unified Engine Sync Effect
  // Handles step changes, code updates, and URL navigation efficiently
  const lastSyncedSlug = useRef<string | null>(null)
  const lastSyncedUrl = useRef<string | null>(null)
  const lastSyncedFiles = useRef<string | null>(null)
  const lastSyncedPagesDir = useRef<string | null>(null)

  useEffect(() => {
    if (!isReady || !engineRef.current) return

    const slugChanged = currentStep.slug !== lastSyncedSlug.current
    const urlChanged = currentUrl !== lastSyncedUrl.current
    const filesJson = JSON.stringify(debouncedFiles)
    const filesChanged = filesJson !== lastSyncedFiles.current
    const pagesDir = currentStep.pagesDir || 'pages'
    const pagesDirChanged = pagesDir !== lastSyncedPagesDir.current

    if (slugChanged) {
      // Only do a full RESTART when pagesDir changed (rare). Otherwise
      // syncPages atomically writes the new file set, deletes leftovers,
      // and invalidates the loader cache — preserving the WS session so
      // we don't trigger the "session expired" toast on every step nav.
      if (pagesDirChanged && lastSyncedPagesDir.current !== null) {
        console.log('[TutorialWorkspace] Step Change Reset (RESTART, pagesDir changed)')
        engineRef.current.restart(currentStep.pagesDir)
        Object.entries(files).forEach(([path, content]) => {
          engineRef.current?.updateFile(path, content)
        })
      } else {
        console.log('[TutorialWorkspace] Step Change Sync (incremental)')
        engineRef.current.syncPages(pagesDir, files)
      }

      setActiveFile(currentStep.files[0]?.path || 'index.wire')
      lastSyncedSlug.current = currentStep.slug
      lastSyncedFiles.current = JSON.stringify(files)
      lastSyncedPagesDir.current = pagesDir

      // Mark URL as synced as well to prevent double-fire
      lastSyncedUrl.current = currentUrl
      engineRef.current.httpRequest('GET', currentUrl)
      return
    }

    if (filesChanged) {
      console.log('[TutorialWorkspace] Syncing Files (Debounced)')
      // Use syncPages so newly-added or removed files are picked up the
      // same way local `pywire dev` does, without restarting the server.
      engineRef.current.syncPages(pagesDir, debouncedFiles)
      lastSyncedFiles.current = filesJson
      lastSyncedPagesDir.current = pagesDir

      // Reload current URL to reflect changes
      engineRef.current.httpRequest('GET', currentUrl)
      lastSyncedUrl.current = currentUrl
      return
    }

    if (urlChanged) {
      console.log('[TutorialWorkspace] URL Navigation')
      engineRef.current.httpRequest('GET', currentUrl)
      lastSyncedUrl.current = currentUrl
    }
  }, [isReady, currentStep.slug, currentUrl, debouncedFiles])

  // Live iframe text — read from the actual DOM to capture reactive/interactive state
  const [liveIframeText, setLiveIframeText] = useState('')

  useEffect(() => {
    if (!currentStep.successCriteria) return
    // Poll iframe text content to detect interactive state changes (button clicks, etc.)
    const interval = setInterval(() => {
      const iframe = document.querySelector('iframe') as HTMLIFrameElement | null
      const text = iframe?.contentDocument?.body?.innerText || ''
      setLiveIframeText((prev) => (prev !== text ? text : prev))
    }, 500)
    return () => clearInterval(interval)
  }, [currentStep.successCriteria])

  // Validation Effect
  useEffect(() => {
    if (!currentStep.successCriteria) return

    let isMounted = true

    const runValidation = async () => {
      const results = await SuccessValidator.validate(
        files,
        currentStep.successCriteria!,
        lastRenderedHtml,
        (path) => engineRef.current?.fetchRouteContent(path) || Promise.resolve(''),
        liveIframeText,
      )

      if (!isMounted) return

      // Expose results for TasksChecklist later
      setValidationResults(results)

      const allPassed = results.every((r) => r.passed)

      if (allPassed && !isCompleted) {
        setIsCompleted(true)
        // Optionally play sound or show confetti here
      } else if (!allPassed && isCompleted) {
        setIsCompleted(false)
      }
    }

    runValidation()

    return () => {
      isMounted = false
    }
  }, [files, lastRenderedHtml, liveIframeText, currentStep.successCriteria, isCompleted])

  // Reset completion on step change
  useEffect(() => {
    setIsCompleted(false)
    setValidationResults([])
    setLastRenderedHtml('')
  }, [currentStep.slug])

  if (!isReady) {
    return (
      <div className="flex items-center justify-center h-full w-full">
        <LoadingSpinner message={loadingMessage} />
      </div>
    )
  }

  return (
    <div className="pw-workspace-container bg-[#03060a]">
      {/* Refined Header inspired by Svelte Tutorial */}
      <header className="pw-header relative">
        {/* TutorialHierarchy moved outside so it can escape overflow:hidden */}

        <div className="pw-header-group">
          <button
            className={`pw-btn-icon-sm ${hierarchyOpen ? 'bg-[var(--pw-border)] text-[var(--pw-text-main)]' : ''}`}
            title="Menu"
            onClick={() => setHierarchyOpen(!hierarchyOpen)}
          >
            <Menu size={18} />
          </button>
          <div className="flex items-center gap-1 ml-2">
            {prevStep ? (
              <a
                href={getStepUrl(prevStep.slug)}
                className="pw-btn-icon-sm"
                title={`Previous: ${prevStep.title}`}
              >
                <ArrowLeft size={18} />
              </a>
            ) : (
              <div className="pw-btn-icon-sm disabled">
                <ArrowLeft size={18} />
              </div>
            )}
            {nextStep ? (
              <a
                href={getStepUrl(nextStep.slug)}
                className={`pw-btn-icon-sm ${isCompleted ? 'success-glow' : ''}`}
                title={`Next: ${nextStep.title}`}
              >
                <ArrowRight size={18} />
              </a>
            ) : (
              <button className="pw-btn-icon-sm" disabled style={{ opacity: 0.3 }} title="Next">
                <ArrowRight size={18} />
              </button>
            )}
          </div>

          <div className="pw-breadcrumb ml-4">
            <span className="pw-breadcrumb-prefix">{currentStep.tutorial || 'Tutorial'}</span>
            <span className="pw-breadcrumb-separator">/</span>
            <span className="pw-breadcrumb-prefix">{currentStep.section}</span>
            {currentStep.section && <span className="pw-breadcrumb-separator">/</span>}
            <span className="pw-breadcrumb-title">{currentStep.title}</span>
          </div>
        </div>

        <div className="pw-header-group">
          <button className="pw-btn-solve mr-2" onClick={solveFiles} title="Show solution">
            solve
          </button>
          <button
            className="pw-btn-icon-sm mr-2"
            onClick={handleResetClick}
            title="Reset to initial code (Cmd/Ctrl + Click to reset ALL progress)"
          >
            <RotateCcw size={18} />
          </button>
        </div>
      </header>

      <div className="pw-workspace-main">
        <Group orientation="horizontal" className="h-full">
          {/* Left: Instructions */}
          {/* Left: Instructions */}
          <Panel
            defaultSize={'30%'}
            minSize={'20%'}
            className="h-full border-r border-[var(--sl-color-border)] bg-[var(--sl-color-bg)]"
          >
            <div className="h-full overflow-y-auto pw-instructions-container">
              {/* We now use native Starlight markdown passed as children */}
              <div className="pw-markdown-content sl-markdown-content p-8 max-w-3xl mx-auto pb-20">
                <MarkdownRenderer content={currentStep.content || ''} />
              </div>
              <TasksChecklist criteria={currentStep.successCriteria} results={validationResults} />
            </div>
          </Panel>

          <Separator className="pw-separator-h" />

          {/* Right: Work Area (Split Top/Bottom) */}
          <Panel defaultSize={'70%'} minSize={'40%'} className="h-full">
            <Group orientation="vertical" className="h-full">
              {/* Top: Files + Editor */}
              <Panel defaultSize={'50%'} minSize={'25%'} className="h-full flex flex-col">
                <Group orientation="horizontal" className="flex-1 min-h-0">
                  <Panel
                    defaultSize={'20%'}
                    minSize={'15%'}
                    className="h-full border-r border-[var(--sl-color-border)] bg-[var(--sl-color-bg)] overflow-y-auto"
                  >
                    <TutorialFileTree
                      files={Object.keys(files)}
                      activeFile={activeFile}
                      onFileSelect={setActiveFile}
                      onFileAdd={handleFileAddRequest}
                      onFileDelete={handleFileDelete}
                      behaviors={currentStep.behaviors}
                      originalFiles={currentStep.files}
                    />
                  </Panel>
                  <Separator className="pw-separator-h" />
                  <Panel defaultSize={'80%'} minSize={'50%'} style={{ height: '100%' }}>
                    <div className="h-full w-full relative overflow-hidden">
                      <Editor
                        content={code}
                        language="pywire"
                        onChange={(newVal) => updateFile(activeFile, newVal)}
                        readOnly={
                          currentStep.files.find((f) => f.path === activeFile)?.editable === false
                        }
                      />
                    </div>
                  </Panel>
                </Group>
              </Panel>

              <Separator className="pw-separator-v" />

              {/* Bottom: Browser Preview */}
              <Panel defaultSize={'50%'} minSize={'25%'} style={{ height: '100%' }}>
                <div className="h-full w-full">
                  <BrowserPreview
                    url={currentUrl}
                    onNavigate={handleNavigate}
                    onBack={handleBack}
                    onForward={handleForward}
                    canBack={urlCursor > 0}
                    canForward={urlCursor < urlStack.length - 1}
                    onMessage={handlePreviewMessage}
                    theme={theme}
                  />
                </div>
              </Panel>
            </Group>
          </Panel>
        </Group>
      </div>

      {/* Modals */}
      <Modal
        isOpen={modal.isOpen}
        onClose={() => setModal({ ...modal, isOpen: false })}
        title={modal.title || 'Action Not Allowed'}
      >
        <div className="pw-modal-body">
          <p>{modal.message}</p>
          {modal.allowedItems && modal.allowedItems.length > 0 && (
            <ul className="pw-modal-list mt-3">
              {modal.allowedItems.map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
          )}
        </div>
        <div className="pw-modal-footer">
          <button className="pw-btn-primary" onClick={() => setModal({ ...modal, isOpen: false })}>
            OK
          </button>
        </div>
      </Modal>

      <Modal
        isOpen={resetConfirmModal}
        onClose={() => setResetConfirmModal(false)}
        title="Reset All Progress?"
      >
        <div className="pw-modal-body">
          <p>
            This will reset your code changes for <strong>ALL</strong> tutorial steps. This action
            cannot be undone.
          </p>
        </div>
        <div className="pw-modal-footer">
          <button className="pw-btn-secondary" onClick={() => setResetConfirmModal(false)}>
            Cancel
          </button>
          <button
            className="pw-btn-danger"
            onClick={() => {
              resetAll()
              setResetConfirmModal(false)
              window.location.reload()
            }}
          >
            Reset All
          </button>
        </div>
      </Modal>

      <Modal
        isOpen={!!inputModal?.isOpen}
        onClose={() => setInputModal(null)}
        title={`Create New ${inputModal?.isFolder ? 'Folder' : 'File'}`}
      >
        <div className="pw-modal-body">
          <p className="mb-3 text-dim">
            {inputModal?.folderPath
              ? `Creating in ${inputModal.folderPath}`
              : 'Creating in project root'}
          </p>
          <input
            autoFocus
            className="pw-input w-full"
            placeholder={`Enter ${inputModal?.isFolder ? 'folder' : 'file'} name...`}
            value={inputName}
            onChange={(e) => setInputName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleFileAddSubmit()}
          />
        </div>
        <div className="pw-modal-footer">
          <button className="pw-btn-secondary" onClick={() => setInputModal(null)}>
            Cancel
          </button>
          <button className="pw-btn-primary" onClick={handleFileAddSubmit}>
            Create
          </button>
        </div>
      </Modal>

      {isCompleted && (
        <div className="pw-success-banner">
          <CheckCircle size={20} />
          <span>Tutorial Step Complete!</span>
        </div>
      )}

      {/* TutorialHierarchy rendered here - outside all overflow:hidden containers */}
      {/* TutorialHierarchy rendered here - outside all overflow:hidden containers */}
      <TutorialHierarchy
        allSteps={allSteps}
        currentSlug={currentSlug}
        getStepUrl={getStepUrl}
        isOpen={hierarchyOpen}
        onClose={() => setHierarchyOpen(false)}
      />
    </div>
  )
}

function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState(value)
  useEffect(() => {
    const handler = setTimeout(() => setDebouncedValue(value), delay)
    return () => clearTimeout(handler)
  }, [value, delay])
  return debouncedValue
}
