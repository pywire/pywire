import React, { useEffect, useRef, useCallback } from 'react'

interface PreviewProps {
  url: string
  onMessage?: (message: any) => void
  theme?: 'light' | 'dark'
}

const INJECTED_SCRIPT = `
(function() {
  const DEBUG_PREVIEW = false;
  if (DEBUG_PREVIEW) console.log('[PreviewScript] Injected script started');
  
  // 1. Override WebSocket
  class MockWebSocket extends EventTarget {
    static get CONNECTING() { return 0; }
    static get OPEN() { return 1; }
    static get CLOSING() { return 2; }
    static get CLOSED() { return 3; }

    constructor(url) {
      super();
      
      // Fix invalid URLs from doc.write iframe (which often has empty host)
      if (url.startsWith('ws:///')) {
        url = 'ws://localhost' + url.substring(5);
      }
      
      
      if (DEBUG_PREVIEW) console.log('[MockWS] Connecting to:', url);
      this.url = url;
      this.readyState = 0; // CONNECTING
      
      this._onopen = null;
      this._onmessage = null;
      this._onclose = null;
      this._onerror = null;
      this._keepaliveTimer = null;

      // PyWire client-side heartbeat (websocket.ts) closes the socket if
      // 40s pass with no inbound message. Server-side _ping_loop is
      // disabled in shim.py (ws_ping_interval=0) because under Pyodide's
      // single-thread, pong from the iframe gets starved behind
      // http_request bursts and trips the 10s pong-deadline → forced
      // close → reconnect storm. With server pings off, nothing else
      // refreshes lastMessageTime on the client, so an idle session
      // disconnects after 40s. Synthesize a self-ping inside the iframe:
      // the client transport handles type:'ping' by responding pong
      // (server pong handler is a noop with ping_loop off) and, more
      // importantly, refreshes lastMessageTime on the inbound path.
      // Bytes are msgpack({type:'ping'}) precomputed.
      const PING_BYTES = new Uint8Array([0x81, 0xa4, 0x74, 0x79, 0x70, 0x65, 0xa4, 0x70, 0x69, 0x6e, 0x67]);

      // Notify parent we want to connect
      window.parent.postMessage({
        type: 'WS_CONNECT',
        payload: { path: url.replace('ws://localhost', '') }
      }, '*');
      
      // Listen for messages from parent
      window.addEventListener('message', (e) => {
        if (DEBUG_PREVIEW) console.log('[MockWS] Raw message event in iframe:', e.data?.type);
        if (e.data && e.data.type === 'WS_MESSAGE') {
          console.log('[MockWS] Received from parent:', e.data.message.type);
          if (e.data.message.type === 'websocket.accept') {
             if (DEBUG_PREVIEW) console.log('[MockWS] WebSocket accepted');
             this.readyState = 1; // OPEN
             this.dispatchEvent(new Event('open'));
             if (this.onopen) {
               if (DEBUG_PREVIEW) console.log('[MockWS] Calling onopen handler');
               this.onopen(new Event('open'));
             }
             if (this._keepaliveTimer === null) {
               this._keepaliveTimer = setInterval(() => {
                 if (this.readyState !== 1) return;
                 const ev = new MessageEvent('message', { data: PING_BYTES.buffer.slice(0) });
                 this.dispatchEvent(ev);
                 if (this.onmessage) this.onmessage(ev);
               }, 15000);
             }
          }
          if (e.data.message.type === 'websocket.send') {
            let data;
            if (e.data.message.bytes && Array.isArray(e.data.message.bytes)) {
              data = new Uint8Array(e.data.message.bytes).buffer;
              console.log('[MockWS] Received binary data from parent, length:', e.data.message.bytes.length);
            } else if (e.data.message.text) {
              data = e.data.message.text;
              if (DEBUG_PREVIEW) console.log('[MockWS] Received text data from parent');
            }
            
            if (data) {
              const event = new MessageEvent('message', { data: data });
              this.dispatchEvent(event);
              if (this.onmessage) this.onmessage(event);
            }
          }
          if (e.data.message.type === 'websocket.close') {
             if (DEBUG_PREVIEW) console.log('[MockWS] WebSocket closed by server');
             this.readyState = 3; // CLOSED
             if (this._keepaliveTimer !== null) {
               clearInterval(this._keepaliveTimer);
               this._keepaliveTimer = null;
             }
             this.dispatchEvent(new Event('close'));
             if (this.onclose) this.onclose(new Event('close'));
          }
        }
      });
    }

    get onopen() { return this._onopen; }
    set onopen(fn) { this._onopen = fn; }
    get onmessage() { return this._onmessage; }
    set onmessage(fn) { this._onmessage = fn; }
    get onclose() { return this._onclose; }
    set onclose(fn) { this._onclose = fn; }
    get onerror() { return this._onerror; }
    set onerror(fn) { this._onerror = fn; }
    
    send(data) {
      // Handle binary data (msgpack) by converting to array for postMessage
      let serializedData = data;
      if (data instanceof ArrayBuffer) {
        serializedData = Array.from(new Uint8Array(data));
      } else if (data instanceof Uint8Array) {
        serializedData = Array.from(data);
      }
      if (DEBUG_PREVIEW) console.log('[MockWS] Sending to parent, type:', typeof serializedData, 'isArray:', Array.isArray(serializedData), 'length:', Array.isArray(serializedData) ? serializedData.length : 'N/A');
      window.parent.postMessage({
        type: 'WS_SEND',
        payload: { data: serializedData }
      }, '*');
    }
    
    close() {
      if (DEBUG_PREVIEW) console.log('[MockWS] WebSocket closed');
      this.readyState = 3; // CLOSED
      if (this._keepaliveTimer !== null) {
        clearInterval(this._keepaliveTimer);
        this._keepaliveTimer = null;
      }
      // Notify parent so it can tear down the server-side connection in
      // the Pyodide adapter. Without this, each iframe doc.write leaves
      // a zombie ASGI WebSocket alive in the in-Pyodide PyWire app
      // whose ping_loop keeps running and eventually logs
      // 'WebSocket ping timeout, closing connection'. They accumulate
      // and starve real connections.
      try {
        window.parent.postMessage({ type: 'WS_DISCONNECT', payload: {} }, '*');
      } catch (_) {}
      this.dispatchEvent(new Event('close'));
      if (this.onclose) this.onclose(new Event('close'));
    }
  }
  
  window.WebSocket = MockWebSocket;

  // 2. Intercept Clicks for SPA navigation and Debugging
  document.addEventListener('click', (e) => {
    const target = e.target;
    if (DEBUG_PREVIEW) console.log('[PreviewScript] Document click on:', target.tagName, target.className, target.id);
    
    const link = target.closest('a');
    if (link && link.href.startsWith(window.location.origin)) {
      if (DEBUG_PREVIEW) console.log('[PreviewScript] Intercepting SPA link click:', link.href);
      e.preventDefault();
      const path = link.getAttribute('href');
      window.parent.postMessage({
        type: 'NAVIGATE',
        payload: { path: path }
      }, '*');
      return;
    }

    // Log if it has data-on-click
    const clickable = target.closest('[data-on-click]');
    if (clickable) {
      if (DEBUG_PREVIEW) console.log('[PreviewScript] Clicked element with data-on-click:', clickable.getAttribute('data-on-click'));
    } else {
      if (DEBUG_PREVIEW) console.log('[PreviewScript] Clicked element WITHOUT data-on-click');
    }
  });

  // Log all script tags to ensure pywire is present
  if (DEBUG_PREVIEW) console.log('[PreviewScript] Script tags present:', Array.from(document.querySelectorAll('script')).map(s => s.src || 'inline'));
})();
`

const DEBUG_PREVIEW = true // Temporary enable for debugging

const getStylesInner = (theme: 'light' | 'dark') => `
  :root {
    /* Light theme variables */
    --bg: #ffffff;
    --fg: #1f2937;
    --border: #e5e7eb;
    --primary: #0ea5e9;
    --primary-hover: #0284c7;
    --surface: #f3f4f6;
    --code-bg: #f3f4f6;
  }

  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #171717;
      --fg: #e5e7eb;
      --border: #404040;
      --surface: #262626;
      --code-bg: #262626;
    }
  }

  /* Override with explicit theme prop */
  ${
    theme === 'dark'
      ? `
    :root {
      --bg: #171717;
      --fg: #e5e7eb;
      --border: #404040;
      --surface: #262626;
      --code-bg: #262626;
    }
  `
      : `
    :root {
      --bg: #ffffff;
      --fg: #1f2937;
      --border: #e5e7eb;
      --surface: #f3f4f6;
      --code-bg: #f3f4f6;
    }
  `
  }

  body {
    background-color: var(--bg);
    color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen-Sans, Ubuntu, Cantarell, "Helvetica Neue", sans-serif;
    margin: 0;
    padding: 2rem;
    line-height: 1.5;
    transition: background-color 0.2s, color 0.2s;
  }

  h1, h2, h3, h4, h5, h6 {
    margin: 0 0 0.5em 0;
    font-weight: 700;
    line-height: 1.2;
  }

  h1 { font-size: 2em; }
  h2 { font-size: 1.5em; }
  
  p { margin: 0 0 1em 0; }

  button {
    font-family: inherit;
    font-size: inherit;
    padding: 0.4em 0.8em;
    color: white;
    background-color: var(--primary);
    border: none;
    border-radius: 4px;
    cursor: pointer;
    transition: background-color 0.1s;
  }

  button:hover {
    background-color: var(--primary-hover);
  }

  button:active {
    transform: translateY(1px);
  }

  input, textarea, select {
    font-family: inherit;
    font-size: inherit;
    padding: 0.4em;
    margin: 0 0 0.5em 0;
    box-sizing: border-box;
    border: 1px solid var(--border);
    border-radius: 4px;
    background-color: var(--surface);
    color: var(--fg);
  }

  input:focus, textarea:focus, select:focus {
    outline: 2px solid var(--primary);
    outline-offset: -1px;
  }

  /* Utilities that might be useful for layout */
  .stack { display: flex; flex-direction: column; gap: 0.5em; }
  .row { display: flex; gap: 0.5em; align-items: center; }

  code {
      font-family: menlo, inconsolata, monospace;
      font-size: 0.9em;
      color: var(--fg);
      background-color: var(--code-bg);
      padding: 0.2em 0.4em;
      border-radius: 3px;
  }
  
  pre {
      background-color: var(--code-bg);
      padding: 1em;
      border-radius: 4px;
      overflow-x: auto;
  }

  a {
      color: var(--primary);
      text-decoration: none;
  }
  
  a:hover {
      text-decoration: underline;
  }
  
  ul, ol {
      padding-left: 2em;
      margin: 0 0 1em 0;
  }
`

export const Preview: React.FC<PreviewProps> = ({ url, onMessage, theme = 'dark' }) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const iframeRef = useRef<HTMLIFrameElement | null>(null)

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      onMessage?.(event.data)
    }

    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
  }, [onMessage])

  // Reactive Theme Switching
  useEffect(() => {
    const iframe = iframeRef.current
    if (iframe && iframe.contentDocument) {
      const body = iframe.contentDocument.body
      if (body) {
        body.style.backgroundColor = theme === 'dark' ? '#171717' : '#ffffff'
        body.style.color = theme === 'dark' ? '#e5e7eb' : '#1f2937'
      }
    }
  }, [theme])

  // Track if we've done the initial document setup
  const isInitialized = useRef(false)

  // Reset when URL changes (navigation) to require fresh document setup
  useEffect(() => {
    isInitialized.current = false
  }, [url])

  // Replace the iframe element with a fresh one. Critical: doc.open()/write()
  // does NOT reset the iframe's window object — globals, including setInterval
  // timers from prior PyWireApp instances created by re-running the bundled
  // IIFE script tag, persist forever. Each edit cycle leaks another live
  // heartbeat timer; eventually one of them times out, triggering reconnects
  // and the "session expired" UX. Replacing the <iframe> element gives a
  // brand-new window and kills all stale timers in one shot.
  const replaceIframe = useCallback((): HTMLIFrameElement | null => {
    const container = containerRef.current
    if (!container) return null
    const old = iframeRef.current
    const next = document.createElement('iframe')
    next.style.width = '100%'
    next.style.height = '100%'
    next.style.border = 'none'
    next.title = 'Preview'
    container.appendChild(next)
    if (old && old.parentNode === container) {
      container.removeChild(old)
    }
    iframeRef.current = next
    return next
  }, [])

  // Helper to get processed HTML and styles
  const getProcessedContent = useCallback(
    (html: string) => {
      // Rewrite /_pywire/static/ script srcs to blob URLs extracted from the
      // installed pywire package (sent by the worker via STATIC_FILES message).
      // This eliminates the need to pre-copy client JS into docs/public/.
      const blobUrls = (window as any).__PYWIRE_STATIC_BLOB_URLS__ as
        | Record<string, string>
        | undefined
      let processedHtml = html
      if (blobUrls) {
        processedHtml = processedHtml.replace(
          /src="\/_pywire\/static\/([^"?]+)(\?[^"]*)?"/g,
          (_match, filename: string) => {
            const blobUrl = blobUrls[filename]
            if (blobUrl) return `src="${blobUrl}"`
            // Fallback: serve from Astro public dir (shouldn't happen)
            const baseUrl = import.meta.env.BASE_URL.endsWith('/')
              ? import.meta.env.BASE_URL
              : `${import.meta.env.BASE_URL}/`
            return `src="${baseUrl}_pywire/static/${filename}"`
          },
        )
      } else {
        // Blob URLs not ready yet — fall back to Astro public dir
        const baseUrl = import.meta.env.BASE_URL.endsWith('/')
          ? import.meta.env.BASE_URL
          : `${import.meta.env.BASE_URL}/`
        processedHtml = processedHtml.replace(/src="\/_pywire\//g, `src="${baseUrl}_pywire/`)
      }
      const isFullDocument = /<html/i.test(processedHtml) || /<!DOCTYPE/i.test(processedHtml)

      const styles = `
      <style id="pw-injected-styles">
        ${getStylesInner(theme)}
      </style>
    `

      return { processedHtml, isFullDocument, styles }
    },
    [theme],
  )

  // initContent: Full document setup via doc.write (used for HTTP responses / code changes)
  // This creates a fresh document with new MockWebSocket connection
  const initContent = useCallback(
    (html: string) => {
      if (DEBUG_PREVIEW) console.log('[Preview] initContent called (replace iframe)')
      const iframe = replaceIframe()
      if (iframe && iframe.contentDocument) {
        const doc = iframe.contentDocument
        const { processedHtml, isFullDocument, styles } = getProcessedContent(html)

        // Intentionally NOT calling history.pushState here. Same-origin
        // iframes share the joint session history with the host page,
        // so pushState entries from this iframe accumulate alongside
        // parent entries. Calling iframe.history.back() then walks the
        // joint history and can leak past the iframe into the docs page.
        // The parent owns the URL stack; we just render content.
        const pushStateScript = ''

        let finalHtml = ''

        if (isFullDocument) {
          finalHtml = processedHtml
          if (finalHtml.includes('<head>')) {
            finalHtml = finalHtml.replace(
              '<head>',
              `<head>${styles}<script>${INJECTED_SCRIPT}</script>`,
            )
          } else if (finalHtml.includes('<html>')) {
            finalHtml = finalHtml.replace(
              '<html>',
              `<html><head>${styles}<script>${INJECTED_SCRIPT}</script></head>`,
            )
          } else {
            finalHtml = `${styles}<script>${INJECTED_SCRIPT}</script>${finalHtml}`
          }
          if (finalHtml.includes('</body>')) {
            finalHtml = finalHtml.replace('</body>', `${pushStateScript}</body>`)
          } else {
            finalHtml += pushStateScript
          }
        } else {
          finalHtml = `
          <!DOCTYPE html>
          <html>
            <head>
              <meta charset="UTF-8">
              ${styles}
              <script>${INJECTED_SCRIPT}</script>
            </head>
            <body>
              ${processedHtml}
              ${pushStateScript}
            </body>
          </html>
        `
        }

        doc.open()
        ;(doc as any).write(finalHtml)
        doc.close()
        isInitialized.current = true
      }
    },
    [url, theme, getProcessedContent, replaceIframe],
  )

  // patchContent: Incremental update via innerHTML (used for WebSocket updates)
  // This preserves the existing MockWebSocket connection and page state
  const patchContent = useCallback(
    (html: string) => {
      if (DEBUG_PREVIEW) console.log('[Preview] patchContent called (innerHTML only)')
      if (iframeRef.current && iframeRef.current.contentDocument) {
        const doc = iframeRef.current.contentDocument

        // If not initialized yet, fall back to full init
        if (!isInitialized.current || !doc.body) {
          if (DEBUG_PREVIEW)
            console.log('[Preview] patchContent: not initialized, falling back to initContent')
          initContent(html)
          return
        }

        const { processedHtml, isFullDocument } = getProcessedContent(html)

        // Extract body content from processedHtml
        let bodyContent = processedHtml
        if (isFullDocument) {
          const bodyMatch = processedHtml.match(/<body[^>]*>([\s\S]*)<\/body>/i)
          if (bodyMatch && bodyMatch[1]) {
            bodyContent = bodyMatch[1]
          }
        }

        // Update body innerHTML only
        doc.body.innerHTML = bodyContent

        // Update styles if theme changed
        const existingStyles = doc.getElementById('pw-injected-styles')
        if (existingStyles) {
          existingStyles.innerHTML = getStylesInner(theme)
        }
      }
    },
    [theme, getProcessedContent, initContent],
  )

  // Expose methods to parent
  useEffect(() => {
    const targetWindow = window

    ;(targetWindow as any).__PYWIRE_INIT_PREVIEW__ = initContent
    ;(targetWindow as any).__PYWIRE_PATCH_PREVIEW__ = patchContent
    // Keep this for generic use, map to initContent
    ;(targetWindow as any).__PYWIRE_UPDATE_PREVIEW__ = initContent
    // BACK/FORWARD are owned by BrowserPreview/TutorialWorkspace via a
    // parent-side url stack. Do NOT expose iframe.history.back() — see
    // comment in initContent re: joint session history.
    ;(targetWindow as any).__PYWIRE_PREVIEW_RELOAD__ = () => {
      if (DEBUG_PREVIEW) console.log('[Preview] Executing iframe reload (manual HTTP request)')
      window.parent.postMessage(
        {
          type: 'HTTP_REQUEST',
          payload: { method: 'GET', path: url || '/', headers: {} },
        },
        '*',
      )
    }
    ;(targetWindow as any).__PYWIRE_SEND_TO_PREVIEW__ = (data: any) => {
      const iframe = iframeRef.current
      if (iframe && iframe.contentWindow) {
        iframe.contentWindow.postMessage(
          {
            type: 'WS_MESSAGE',
            message: data.message,
          },
          '*',
        )
      }
    }

    return () => {
      delete (targetWindow as any).__PYWIRE_INIT_PREVIEW__
      delete (targetWindow as any).__PYWIRE_PATCH_PREVIEW__
      delete (targetWindow as any).__PYWIRE_UPDATE_PREVIEW__
      delete (targetWindow as any).__PYWIRE_PREVIEW_RELOAD__
      delete (targetWindow as any).__PYWIRE_SEND_TO_PREVIEW__
    }
  }, [url, initContent, patchContent])

  return <div ref={containerRef} style={{ height: '100%', width: '100%', overflow: 'hidden' }} />
}
