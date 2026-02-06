import sys
import json
import asyncio
import traceback
import traceback
from pywire import PyWire

DEBUG_SHIM = False

# 1. Initialize App (Lazy)
# We wait to initialize until the first request to ensure FS is ready
app_instance = None
current_pages_dir = "/app" # Default

import re

# Helper to escape @ and $ attributes for lxml compatibility in Pyodide
def escape_pywire_content(content: str) -> str:
    if "---html---" not in content.lower():
        return content
        
    parts = re.split(r"(---html---)", content, flags=re.IGNORECASE, maxsplit=1)
    if len(parts) < 3:
        return content
        
    python_part = parts[0]
    separator = parts[1]
    html_part = parts[2]
    
    # Escape @click -> __pw_on_click and $model -> __pw_dir_model
    # We look for @ or $ followed by word characters, dots, or dashes, followed by = or {
    # but only if preceded by whitespace or <
    html_part = re.sub(r'(?<=[\s<])@([a-zA-Z0-9._-]+)(?==|\{)', r'__pw_on_\1', html_part)
    html_part = re.sub(r'(?<=[\s<])\$([a-zA-Z0-9._-]+)(?==|\{)', r'__pw_dir_\1', html_part)
    
    return python_part + separator + html_part

def get_app():
    global app_instance, current_pages_dir
    if app_instance is None:
        try:
            print(f"Initializing PyWire app with pages_dir={current_pages_dir}...")
            
            # Monkey-patch the PyWireParser class to escape @/$ attributes for Pyodide lxml compatibility
            # This must be done BEFORE initializing PyWire so initial load is covered.
            from pywire.compiler.parser import PyWireParser
            if not hasattr(PyWireParser, "_original_parse"):
                PyWireParser._original_parse = PyWireParser.parse
                def patched_parse(self, content, file_path=""):
                    escaped_content = escape_pywire_content(content)
                    return self._original_parse(escaped_content, file_path)
                PyWireParser.parse = patched_parse
                print("PyWireParser class monkey-patched for Pyodide")

            app_instance = PyWire(pages_dir=current_pages_dir, debug=True)
            app_instance._is_dev_mode = True
            
            print("PyWire app initialized successfully")
        except Exception as e:
            print(f"Failed to initialize PyWire app: {repr(e)}")
            traceback.print_exc()
            raise
    return app_instance

# 2. ASGI Adapter
async def run_asgi(scope, receive_queue, send_callback):
    """
    Runs the ASGI app for a single request/socket.
    """
    async def receive():
        return await receive_queue.get()

    async def send(message):
        # Convert bytes to list/str for JS transfer
        if "body" in message and isinstance(message["body"], bytes):
            # Convert body to string (assuming text for tutorial)
            # or list of ints if binary is needed, but text is easier for debug
            try:
                message["body"] = message["body"].decode("utf-8")
            except UnicodeDecodeError:
                message["body"] = list(message["body"])
        
        if "headers" in message:
            # Decode headers from bytes to strings
            decoded_headers = []
            for k, v in message["headers"]:
                k_str = k.decode("utf-8") if isinstance(k, bytes) else k
                v_str = v.decode("utf-8") if isinstance(v, bytes) else v
                decoded_headers.append((k_str, v_str))
            message["headers"] = decoded_headers

        send_callback(message)

    try:
        app = get_app()
        await app(scope, receive, send)
    except Exception as e:
        print(f"ASGI Error: {e}")
        traceback.print_exc()

# 3. Global Request Handler (Called from JS)
# Store active websockets queues
connections = {}

async def handle_js_message(event_data):
    try:
        from pyodide.ffi import to_js
        event_type = event_data.get("type")
        req_id = event_data.get("id")
        if DEBUG_SHIM:
            print(f"DEBUG: shim received JS message: type={event_type} id={req_id}")

        if event_type == "http_request":
            if DEBUG_SHIM:
                print(f"DEBUG: HTTP Request: {event_data['method']} {event_data['path']}")
            # Construct ASGI Scope
            scope = {
                "type": "http",
                "http_version": "1.1",
                "method": event_data["method"],
                "path": event_data["path"],
                "root_path": "",
                "scheme": "http",
                "query_string": b"",
                "headers": [(k.lower().encode(), v.encode()) for k, v in event_data["headers"].items()],
                "server": ("localhost", 80),
                "client": ("client", 0),
            }
            
            queue = asyncio.Queue()
            # Feed initial body if present
            if event_data.get("body"):
                body = event_data["body"]
                if isinstance(body, list):
                    body = bytes(body)
                queue.put_nowait({"type": "http.request", "body": body})
            else:
                queue.put_nowait({"type": "http.request", "body": b""})
            
            # Define callback to send data back to JS
            def send_to_js(msg):
                import js
                if msg.get("type") == "http.response.body":
                     body = msg.get("body", "")
                     if DEBUG_SHIM:
                         print(f"DEBUG: HTTP Response Body length: {len(body)}")
                if DEBUG_SHIM:
                    print(f"DEBUG: Internal ASGI send for HTTP: {msg.get('type')}")
                response_payload = {
                    "type": "http_response",
                    "id": req_id,
                    "message": msg
                }
                js_payload = to_js(response_payload, dict_converter=js.Object.fromEntries)
                js.postMessage(js_payload)

            await run_asgi(scope, queue, send_to_js)

        elif event_type == "ws_connect":
            # Clean path: remove scheme/host/port if present
            # The input might be ":4321/_pywire/ws" or similar due to JS string replacement issues
            path = event_data["path"]
            if "://" in path:
                from urllib.parse import urlparse
                path = urlparse(path).path
            elif path.startswith(":"):
                # Strip port part ":4321"
                slash_idx = path.find("/")
                if slash_idx != -1:
                    path = path[slash_idx:]
            
            if DEBUG_SHIM:
                print(f"DEBUG: Cleaned WS Path: {path}")

            scope = {
                "type": "websocket",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "scheme": "ws",
                "path": path,
                "root_path": "",
                "query_string": b"",
                "headers": [(k.lower().encode(), v.encode()) for k, v in event_data.get("headers", {}).items()],
                "server": ("localhost", 80),
                "client": ("client", 0),
            }
            queue = asyncio.Queue()
            connections[req_id] = queue
            
            def send_to_js(msg):
                import js
                print(f"DEBUG: Internal WS send for {req_id}: type={msg.get('type')}")
                
                if msg.get("type") == "websocket.close":
                    if DEBUG_SHIM:
                        print(f"DEBUG: WebSocket closed by app. Code: {msg.get('code')}")

                # For websocket.send messages, try to decode msgpack payload
                decoded_payload = None
                is_modified = False

                if msg.get("type") == "websocket.send" and "bytes" in msg and isinstance(msg["bytes"], bytes):
                    try:
                        import msgpack
                        decoded_payload = msgpack.unpackb(msg["bytes"])
                        
                        # Fix 2: Sanitize nested HTML in updates (Server -> Client)
                        if isinstance(decoded_payload, dict):
                            if decoded_payload.get("type") == "update" and "html" in decoded_payload:
                                html_content = decoded_payload["html"]
                                lower_html = html_content.lower()
                                if "<html" in lower_html or "<!doctype" in lower_html:
                                    import re
                                    # Extract content inside <body>...</body>
                                    # Extract content inside <body>...</body> using a more robust regex
                                    body_match = re.search(r"<body[\s>](.*?)</body>", html_content, re.IGNORECASE | re.DOTALL)
                                    if not body_match:
                                        # Fallback: maybe body has attributes? <body class="foo">
                                        # The previous regex <body[^>]*> covers it, but let's be sure.
                                        # Let's try splitting by body tag
                                        parts = re.split(r"<body[^>]*>", html_content, flags=re.IGNORECASE)
                                        if len(parts) > 1:
                                            # Take everything after the first <body> match
                                            # And then strip </body> and anything after
                                            content = parts[1]
                                            content = re.split(r"</body>", content, flags=re.IGNORECASE)[0]
                                            decoded_payload["html"] = content
                                            is_modified = True
                                            if DEBUG_SHIM:
                                                print("DEBUG: Stripped full HTML wrapper (fallback method)")
                                    
                                    if body_match and not is_modified:

                                        decoded_payload["html"] = body_match.group(1)
                                        is_modified = True
                                        if DEBUG_SHIM:
                                            print("DEBUG: Stripped full HTML wrapper from Server->Client update payload")

                        if DEBUG_SHIM:
                            print(f"DEBUG: Decoded WS payload: {decoded_payload}")
                    except Exception as e:
                        if DEBUG_SHIM:
                            print(f"DEBUG: Failed to decode/sanitize WS msgpack: {e}")

                # Convert bytes to list for JS transfer
                if "bytes" in msg and isinstance(msg["bytes"], bytes):
                    # Use modified payload if applicable
                    if is_modified and decoded_payload is not None:
                         msg["bytes"] = list(msgpack.packb(decoded_payload))
                    else:
                         msg["bytes"] = list(msg["bytes"])
                
                if "text" in msg and isinstance(msg["text"], bytes):
                    msg["text"] = msg["text"].decode("utf-8")

                response_payload = {
                    "type": "ws_message",
                    "id": req_id,
                    "message": msg
                }
                
                # Include decoded payload if available
                if decoded_payload is not None:
                    response_payload["decoded_payload"] = decoded_payload

                try:
                    js_payload = to_js(response_payload, dict_converter=js.Object.fromEntries)
                    js.postMessage(js_payload)
                    if DEBUG_SHIM:
                        print(f"DEBUG: WS message posted to JS: {msg.get('type')}")
                except Exception as e:
                    print(f"ERROR: Failed to post WS message to JS: {e}")
                    traceback.print_exc()

            # Create a task for the persistent WS connection
            if DEBUG_SHIM:
                print(f"DEBUG: Starting WS ASGI task for {req_id}")
            asyncio.create_task(run_asgi(scope, queue, send_to_js))
            # Initial connect event
            if DEBUG_SHIM:
                print(f"DEBUG: Queuing websocket.connect for {req_id}")
            queue.put_nowait({"type": "websocket.connect"})

        elif event_type == "ws_send":
            queue = connections.get(req_id)
            if queue:
                data = event_data["data"]
                if DEBUG_SHIM:
                    print(f"DEBUG: ws_send received data of type {type(data)}")
                # Data can be a list of bytes (from JS Array) or a string
                if isinstance(data, list):
                    # Convert list of ints back to bytes for msgpack decoding
                    data_bytes = bytes(data)
                    
                    # HACK: Tutorial paths mismatch fix
                    # The client sends {path: "/docs/tutorial", ...} but the worker expects "/"
                    # We need to decode, fix path, and re-encode
                    try:
                        import msgpack
                        payload = msgpack.unpackb(data_bytes)
                        if isinstance(payload, dict) and "path" in payload:
                            original_path = payload["path"]
                            # If path starts with /docs/, rewrite it to /
                            # This aligns the browser's URL with the worker's internal router
                            if original_path.startswith("/docs/"):
                                if DEBUG_SHIM:
                                    print(f"DEBUG: Rewriting path {original_path} -> /")
                                payload["path"] = "/"
                                data_bytes = msgpack.packb(payload)
                    except Exception as e:
                        if DEBUG_SHIM:
                            print(f"DEBUG: Failed to process msgpack in shim: {e}")
                    
                    if DEBUG_SHIM:
                        print(f"DEBUG: ws_send binary data length: {len(data_bytes)}")
                    queue.put_nowait({
                        "type": "websocket.receive", 
                        "bytes": data_bytes
                    })
                else:
                    # Legacy text mode
                    if DEBUG_SHIM:
                        print(f"DEBUG: ws_send text data length: {len(data) if data else 0}")
                    queue.put_nowait({
                        "type": "websocket.receive", 
                        "text": data
                    })
            else:
                if DEBUG_SHIM:
                    print(f"DEBUG: ws_send FAILED: No connection for {req_id}")
    except Exception as e:
        print(f"CRITICAL ERROR in handle_js_message: {e}")
        traceback.print_exc()

# Expose to JS
import js
js.handle_message = handle_js_message

def reload_page(path_str):
    import pathlib
    try:
        app = get_app()
        path = pathlib.Path(path_str)
        # Verify file presence and content
        if path.exists():
            content = path.read_text()
            if DEBUG_SHIM:
                print(f"DEBUG: Reloading {path_str}, content length: {len(content)}")
        else:
            if DEBUG_SHIM:
                print(f"DEBUG: Reloading {path_str}, but file DOES NOT EXIST at that path!")
            
        app.reload_page(path)
        if DEBUG_SHIM:
            print(f"DEBUG: Reloaded: {path_str}")
        return True
    except Exception as e:
        if DEBUG_SHIM:
            print(f"DEBUG: Reload failed for {path_str}: {e}")
        traceback.print_exc()
        return False

js.reload_page = reload_page

def restart_server(pages_dir="/app"):
    global app_instance, current_pages_dir
    print(f"DEBUG: restart_server called with pages_dir={pages_dir}")
    app_instance = None
    current_pages_dir = pages_dir
    # Also invalidate the loader cache
    try:
        from pywire.runtime.loader import get_loader
        get_loader().invalidate_cache()
    except Exception as e:
        print(f"DEBUG: Failed to invalidate loader cache: {e}")

js.restart_server = restart_server
