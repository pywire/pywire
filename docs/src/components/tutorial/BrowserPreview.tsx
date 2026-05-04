import React from 'react'
import { Preview } from './Preview'
import { RefreshCw, Globe, ChevronLeft, ChevronRight } from 'lucide-react'

interface BrowserPreviewProps {
  url: string
  onMessage: (msg: any) => void
  onNavigate?: (path: string) => void
  onBack?: () => void
  onForward?: () => void
  canBack?: boolean
  canForward?: boolean
  theme?: 'light' | 'dark'
}

export const BrowserPreview: React.FC<BrowserPreviewProps> = ({
  url,
  onMessage,
  onNavigate,
  onBack,
  onForward,
  canBack = false,
  canForward = false,
  theme = 'dark',
}) => {
  const [inputValue, setInputValue] = React.useState(url)
  const [isRefreshing, setIsRefreshing] = React.useState(false)
  // Refresh rebuilds the iframe doc (full doc.write), which kills the
  // MockWebSocket and forces a reconnect. Spam-clicking would race
  // multiple reconnects, occasionally tripping the heartbeat timeout
  // path inside the iframe and the "session expired" toast. Rate-limit
  // the button so each click rebuilds at most once per cooldown.
  const lastReloadAt = React.useRef(0)

  // Sync input value with external url prop changes
  React.useEffect(() => {
    setInputValue(url)
  }, [url])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      onNavigate?.(inputValue)
    }
  }

  const handleReload = React.useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    e.nativeEvent.stopImmediatePropagation()

    const now = performance.now()
    if (now - lastReloadAt.current < 500) return
    lastReloadAt.current = now

    setIsRefreshing(true)
    ;(window as any).__PYWIRE_PREVIEW_RELOAD__?.()

    // Reset animation after 500ms (duration of one spin)
    setTimeout(() => setIsRefreshing(false), 500)
  }, [])

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        width: '100%',
        backgroundColor: '#0f1117',
        overflow: 'hidden',
      }}
    >
      {/* URL Bar Area */}
      <div className="pw-browser-url-bar">
        <div className="pw-browser-controls">
          <div className="pw-browser-dot" style={{ backgroundColor: '#ff5f57' }}></div>
          <div className="pw-browser-dot" style={{ backgroundColor: '#febc2e' }}></div>
          <div className="pw-browser-dot" style={{ backgroundColor: '#28c840' }}></div>
        </div>

        <div className="pw-browser-nav">
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              e.nativeEvent.stopImmediatePropagation()
              onBack?.()
            }}
            disabled={!canBack}
            title="Back"
            className="pw-btn-icon"
            style={!canBack ? { opacity: 0.4, cursor: 'not-allowed' } : undefined}
          >
            <ChevronLeft size={16} />
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              e.nativeEvent.stopImmediatePropagation()
              onForward?.()
            }}
            disabled={!canForward}
            title="Forward"
            className="pw-btn-icon"
            style={!canForward ? { opacity: 0.4, cursor: 'not-allowed' } : undefined}
          >
            <ChevronRight size={16} />
          </button>
          <button type="button" onClick={handleReload} title="Reload" className="pw-btn-icon">
            <RefreshCw size={14} className={isRefreshing ? 'pw-spinning' : ''} />
          </button>
        </div>

        <div className="pw-browser-url-display">
          <Globe size={12} style={{ color: 'var(--pw-text-dim)', flexShrink: 0 }} />
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            className="pw-browser-input"
            style={{
              background: 'transparent',
              border: 'none',
              color: 'inherit',
              fontSize: 'inherit',
              width: '100%',
              outline: 'none',
              marginLeft: '4px',
            }}
          />
        </div>
      </div>

      {/* Preview Content */}
      <div style={{ flex: 1, position: 'relative' }}>
        <Preview url={url} onMessage={onMessage} theme={theme} />
      </div>
    </div>
  )
}
