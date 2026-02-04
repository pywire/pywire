import React, { useEffect, useRef, useCallback } from 'react';

interface PreviewProps {
  url: string;
  onMessage?: (message: any) => void;
  theme?: 'light' | 'dark';
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
        type: 'HTTP_REQUEST',
        payload: { method: 'GET', path: path, headers: {} }
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
`;

const DEBUG_PREVIEW = true; // Temporary enable for debugging

export const Preview: React.FC<PreviewProps> = ({ url, onMessage, theme = 'dark' }) => {
  const iframeRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      onMessage?.(event.data);
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [onMessage]);

  // Reactive Theme Switching
  useEffect(() => {
    const iframe = iframeRef.current;
    if (iframe && iframe.contentDocument) {
      const body = iframe.contentDocument.body;
      if (body) {
        body.style.backgroundColor = theme === 'dark' ? '#0f1117' : '#f8fafc';
        body.style.color = theme === 'dark' ? '#e5e7eb' : '#0f172a';
      }
    }
  }, [theme]);

  const updateContent = useCallback((html: string) => {
    if (DEBUG_PREVIEW) console.log('[Preview] updateContent called, html length:', html?.length);
    if (iframeRef.current && iframeRef.current.contentDocument) {
      const doc = iframeRef.current.contentDocument;

      // Handle base path for assets if serving from a subdir (like /docs/)
      const baseUrl = import.meta.env.BASE_URL.endsWith('/')
        ? import.meta.env.BASE_URL
        : `${import.meta.env.BASE_URL}/`;

      // Rewrite asset paths to match Astro's base URL
      // PyWire generates root-relative paths like /_pywire/static/...
      const processedHtml = html.replace(/src="\/_pywire\//g, `src="${baseUrl}_pywire/`);

      if (DEBUG_PREVIEW) console.log('[Preview] Writing to iframe doc, current history length:', doc.defaultView?.history.length);

      doc.open();
      doc.write(`
        <!DOCTYPE html>
        <html>
          <head>
            <meta charset="UTF-8">
            <style>
              body {
                background-color: ${theme === 'dark' ? '#0f1117' : '#f8fafc'};
                color: ${theme === 'dark' ? '#e5e7eb' : '#0f172a'};
                font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                margin: 0;
                padding: 1rem;
              }
              /* Basic reset for h1/p to match tutorial feel */
              h1, h2, h3, h4, h5, h6 { margin-top: 0; }
            </style>
            <script>${INJECTED_SCRIPT}</script>
          </head>
          <body>
            ${processedHtml}
            <script>
              // Update the iframe's URL display (virtual)
              try {
                if (window.location.pathname !== "${url}") {
                  window.history.pushState({ pwPath: "${url}" }, "", "${url}");
                  if (${DEBUG_PREVIEW}) console.log('[PreviewScript] pushState to ${url}');
                }
              } catch (e) {
                if (${DEBUG_PREVIEW}) console.error('[PreviewScript] pushState failed:', e);
              }
            </script>
          </body>
        </html>
      `);
      doc.close();
    }
  }, [url, theme]);

  // Expose methods to parent
  useEffect(() => {
    const targetWindow = window;

    (targetWindow as any).__PYWIRE_UPDATE_PREVIEW__ = updateContent;

    (targetWindow as any).__PYWIRE_PREVIEW_BACK__ = () => {
      const iframe = iframeRef.current;
      if (iframe && iframe.contentWindow) {
        const isParentHistory = iframe.contentWindow.history === window.history;
        if (DEBUG_PREVIEW) {
          console.log('[Preview] Executing iframe history.back()');
          console.log('[Preview] Is iframe history same as parent?', isParentHistory);
          console.log('[Preview] Iframe history length:', iframe.contentWindow.history.length);
        }

        if (!isParentHistory) {
          iframe.contentWindow.history.back();
        } else {
          console.error('[Preview] CRITICAL: Iframe history is identical to parent history!');
        }
      }
    };

    (targetWindow as any).__PYWIRE_PREVIEW_FORWARD__ = () => {
      const iframe = iframeRef.current;
      if (iframe && iframe.contentWindow) {
        if (DEBUG_PREVIEW) console.log('[Preview] Executing iframe history.forward()');
        iframe.contentWindow.history.forward();
      }
    };

    (targetWindow as any).__PYWIRE_PREVIEW_RELOAD__ = () => {
      if (DEBUG_PREVIEW) console.log('[Preview] Executing iframe reload (manual HTTP request)');
      window.parent.postMessage({
        type: 'HTTP_REQUEST',
        payload: { method: 'GET', path: url || '/', headers: {} }
      }, '*');
    };

    (targetWindow as any).__PYWIRE_SEND_TO_PREVIEW__ = (data: any) => {
      const iframe = iframeRef.current;
      if (iframe && iframe.contentWindow) {
        iframe.contentWindow.postMessage({
          type: 'WS_MESSAGE',
          message: data.message
        }, '*');
      }
    };

    return () => {
      delete (targetWindow as any).__PYWIRE_UPDATE_PREVIEW__;
      delete (targetWindow as any).__PYWIRE_PREVIEW_BACK__;
      delete (targetWindow as any).__PYWIRE_PREVIEW_FORWARD__;
      delete (targetWindow as any).__PYWIRE_PREVIEW_RELOAD__;
      delete (targetWindow as any).__PYWIRE_SEND_TO_PREVIEW__;
    };
  }, [url, updateContent]);

  return (
    <div style={{ height: '100%', width: '100%', overflow: 'hidden' }}>
      <iframe
        ref={iframeRef}
        style={{ width: '100%', height: '100%', border: 'none' }}
        title="Preview"
      />
    </div>
  );
};
