import React from 'react'
import { Preview } from './Preview'
import { RefreshCw, Globe, ChevronLeft, ChevronRight } from 'lucide-react'

interface BrowserPreviewProps {
  url: string
  onMessage: (msg: any) => void
  onNavigate?: (path: string) => void
  theme?: 'light' | 'dark'
}

export const BrowserPreview: React.FC<BrowserPreviewProps> = ({
  url,
  onMessage,
  onNavigate,
  theme = 'dark',
}) => {
  const [inputValue, setInputValue] = React.useState(url)
  const [isRefreshing, setIsRefreshing] = React.useState(false)

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
          <div className="pw-browser-dot" style={{ backgroundColor: '#ff5f56' }}></div>
          <div className="pw-browser-dot" style={{ backgroundColor: '#ffbd2e' }}></div>
          <div className="pw-browser-dot" style={{ backgroundColor: '#27c93f' }}></div>
        </div>

        <div className="pw-browser-nav">
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              e.nativeEvent.stopImmediatePropagation()
              ;(window as any).__PYWIRE_PREVIEW_BACK__?.()
            }}
            title="Back"
            className="pw-btn-icon"
          >
            <ChevronLeft size={16} />
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              e.nativeEvent.stopImmediatePropagation()
              ;(window as any).__PYWIRE_PREVIEW_FORWARD__?.()
            }}
            title="Forward"
            className="pw-btn-icon"
          >
            <ChevronRight size={16} />
          </button>
          <button type="button" onClick={handleReload} title="Reload" className="pw-btn-icon">
            <RefreshCw size={14} className={isRefreshing ? 'pw-spinning' : ''} />
          </button>
        </div>

        <div className="pw-browser-url-display">
          <Globe size={12} style={{ color: '#9ca3af', flexShrink: 0 }} />
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
