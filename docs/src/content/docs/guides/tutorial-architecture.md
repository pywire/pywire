---
title: Tutorial Architecture
description: Technical architecture of the PyWire interactive tutorial running in Pyodide.
---

# PyWire Interactive Tutorial Architecture

## 1. Directory Structure

```text
docs/
├── public/
│   ├── grammars/
│   │   └── pywire.tmLanguage.json  # Your syntax grammar
│   └── pywire-worker.js            # The Web Worker entry point
├── src/
│   ├── components/
│   │   └── tutorial/
│   │       ├── Editor.tsx          # Monaco Editor wrapper
│   │       ├── Preview.tsx         # Iframe + Message Handling
│   │       ├── Terminal.tsx        # XTerm.js wrapper
│   │       └── TutorialEngine.ts   # Orchestrator
└── ...
```

## 2. The Python ASGI Shim (`shim.py`)

This python script runs inside Pyodide. It acts as the "Server". It receives JSON events from JavaScript, converts them to ASGI scopes, and runs the PyWire app.

```python
import sys
import json
import asyncio
from pywire import PyWire

# 1. Initialize App
# We assume the user code has been written to /pages
app_instance = PyWire(pages_dir="/pages", debug=True)

# 2. ASGI Adapter
async def run_asgi(scope, receive_queue, send_callback):
    """
    Runs the ASGI app for a single request/socket.
    """
    async def receive():
        return await receive_queue.get()

    async def send(message):
        # Convert bytes to list for JS transfer if needed
        if "body" in message and isinstance(message["body"], bytes):
            message["body"] = list(message["body"])
        send_callback(message)

    await app_instance(scope, receive, send)

# 3. Global Request Handler (Called from JS)
# Store active websockets queues
connections = {}

async def handle_js_message(event_data):
    event_type = event_data.get("type")
    req_id = event_data.get("id")

    if event_type == "http_request":
        # Construct ASGI Scope
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": event_data["method"],
            "path": event_data["path"],
            "headers": [(k.encode(), v.encode()) for k, v in event_data["headers"].items()],
        }
        
        queue = asyncio.Queue()
        # Feed initial body if present
        if event_data.get("body"):
            queue.put_nowait({"type": "http.request", "body": event_data["body"].encode()})
        
        # Define callback to send data back to JS
        def send_to_js(msg):
            import js
            js.postMessage(json.dumps({
                "type": "http_response",
                "id": req_id,
                "message": msg
            }))

        await run_asgi(scope, queue, send_to_js)

    elif event_type == "ws_connect":
        scope = {
            "type": "websocket",
            "path": event_data["path"],
            "headers": [],
        }
        queue = asyncio.Queue()
        connections[req_id] = queue
        
        def send_to_js(msg):
            import js
            js.postMessage(json.dumps({
                "type": "ws_message",
                "id": req_id,
                "message": msg
            }))

        # Create a task for the persistent WS connection
        asyncio.create_task(run_asgi(scope, queue, send_to_js))
        # Initial connect event
        queue.put_nowait({"type": "websocket.connect"})

    elif event_type == "ws_send":
        queue = connections.get(req_id)
        if queue:
            queue.put_nowait({
                "type": "websocket.receive", 
                "text": event_data["data"]
            })

# Expose to JS
import js
js.handle_message = handle_js_message
```

## 3. The Web Worker (`public/pywire-worker.js`)

This worker loads Pyodide, installs dependencies, and manages the file system.

```javascript
importScripts("[https://cdn.jsdelivr.net/pyodide/v0.25.0/full/pyodide.js](https://cdn.jsdelivr.net/pyodide/v0.25.0/full/pyodide.js)");

let pyodide = null;

async function loadPywire() {
  pyodide = await loadPyodide();
  
  // Install dependencies
  await pyodide.loadPackage(["micropip", "lxml", "ssl"]);
  const micropip = pyodide.pyimport("micropip");
  
  // Install Starlette and Dependencies
  await micropip.install("starlette");
  
  // Install PyWire (You'd bundle a wheel or simple zip of your src)
  // For the tutorial, we might mock the package structure or load a whl
  await micropip.install("[https://pywire.dev/dist/pywire-0.0.1-py3-none-any.whl](https://pywire.dev/dist/pywire-0.0.1-py3-none-any.whl)");
  
  // Initialize File System
  pyodide.FS.mkdir("/pages");
  
  // Load the Shim (defined above)
  const shimCode = await fetch("/shim.py").then(r => r.text());
  await pyodide.runPythonAsync(shimCode);
  
  postMessage({ type: "READY" });
}

self.onmessage = async (event) => {
  const { type, payload } = event.data;
  
  if (type === "INIT") {
    await loadPywire();
  } 
  
  else if (type === "UPDATE_FILE") {
    // Write user code to virtual FS
    pyodide.FS.writeFile(`/pages/${payload.filename}`, payload.content);
    // Reload page logic if needed (handled by PyWire loader usually)
  }
  
  else if (type === "REQUEST") {
    // Pass to Python shim
    // We use a small python snippet to call the async handler
    const jsonStr = JSON.stringify(payload);
    await pyodide.runPythonAsync(`
      import json
      import asyncio
      data = json.loads('${jsonStr}')
      asyncio.create_task(handle_js_message(data))
    `);
  }
};

loadPywire();
```

## 4. The Client Transport Interceptor (`Preview.tsx`)

Inside the preview iframe, we cannot use real network requests. We inject a script that overrides `window.WebSocket` and `window.fetch`.

```typescript
const INJECTED_SCRIPT = `
(function() {
  // 1. Override Fetch (for initial page load)
  // Real implementation would be more robust
  
  // 2. Override WebSocket
  class MockWebSocket extends EventTarget {
    constructor(url) {
      super();
      this.readyState = 0; // CONNECTING
      
      // Notify parent we want to connect
      window.parent.postMessage({
        type: 'WS_CONNECT',
        url: url
      }, '*');
      
      // Simulate Open
      setTimeout(() => {
        this.readyState = 1; // OPEN
        this.dispatchEvent(new Event('open'));
      }, 100);
      
      // Listen for messages from parent (Server)
      window.addEventListener('message', (e) => {
        if (e.data.type === 'WS_DATA') {
          this.dispatchEvent(new MessageEvent('message', { data: e.data.payload }));
        }
      });
    }
    
    send(data) {
      window.parent.postMessage({
        type: 'WS_SEND',
        data: data
      }, '*');
    }
  }
  
  window.WebSocket = MockWebSocket;
})();
`;
```

## 5. Configuring Syntax Highlighting (`astro.config.mjs`)

To use your `.tmLanguage` in the docs code blocks:

```javascript
// astro.config.mjs
import fs from 'node:fs';

// Load the grammar file
const pywireGrammar = JSON.parse(
  fs.readFileSync('./public/grammars/pywire.tmLanguage.json', 'utf-8')
);

export default defineConfig({
  // ...
  integrations: [
    starlight({
      // ...
      expressiveCode: {
        // Configure Shiki
        shiki: {
          langs: [
            // Register your custom language
            {
              id: 'pywire',
              scopeName: 'source.pywire', // Must match scopeName in json
              grammar: pywireGrammar,
              aliases: ['wire'],
            },
            // Load python for the python blocks
            import('shiki/langs/python.mjs'), 
            import('shiki/langs/html.mjs'), 
          ],
        },
      },
    }),
  ],
});
```

Now you can use:
````markdown
```pywire
!layout "main"
x = wire(1)
---html---
<div>{x}</div>
```
`