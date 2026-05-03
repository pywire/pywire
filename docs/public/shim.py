"""Pyodide shim for the PyWire docs interactive tutorial.

This is the JS interop layer that bridges the tutorial's Web Worker
with the PyodideASGIAdapter. The ASGI bridging logic lives in
pywire.adapters.pyodide — this file only handles JS postMessage I/O.
"""

import asyncio
import traceback

from pywire import PyWire
from pywire.adapters.pyodide import PyodideASGIAdapter

# Lazy initialization — wait until first request so virtual FS is ready
app_instance = None
adapter = None
current_pages_dir = "/app"


def get_adapter():
    global app_instance, adapter, current_pages_dir
    if adapter is None:
        try:
            # PyWire derives project_root from caller_dir + marker files
            # (pyproject.toml, .git, .venv). None of those exist in the
            # Pyodide virtual FS, so the project root never lands on
            # sys.path and `from components.badge import Badge` fails.
            # Add the pages_dir's parent (the project root by convention)
            # explicitly so PyWireFinder can resolve sibling component
            # packages like /app/components/badge.wire.
            import os
            import sys
            project_root = os.path.dirname(current_pages_dir.rstrip("/")) or "/app"
            if project_root not in sys.path:
                sys.path.insert(0, project_root)

            print(f"Initializing PyWire app with pages_dir={current_pages_dir}...")
            app_instance = PyWire(pages_dir=current_pages_dir, debug=True)
            app_instance._is_dev_mode = True
            adapter = PyodideASGIAdapter(app_instance)
            print("PyWire app initialized successfully")
        except Exception as e:
            print(f"Failed to initialize PyWire app: {repr(e)}")
            traceback.print_exc()
            raise
    return adapter


async def handle_js_message(event_data):
    """Route incoming JS messages to the adapter."""
    try:
        from pyodide.ffi import to_js
        import js

        event_type = event_data.get("type")
        req_id = event_data.get("id")

        if event_type == "http_request":
            adp = get_adapter()
            headers = dict(event_data.get("headers", {}))
            body = b""
            if event_data.get("body"):
                raw = event_data["body"]
                body = bytes(raw) if isinstance(raw, list) else raw

            status, resp_headers, body_text = await adp.fetch(
                method=event_data["method"],
                path=event_data["path"],
                headers=headers,
                body=body,
            )

            response = {
                "type": "http_response",
                "id": req_id,
                "message": {
                    "type": "http.response.body",
                    "status": status,
                    "headers": resp_headers,
                    "body": body_text,
                },
            }
            js.postMessage(to_js(response, dict_converter=js.Object.fromEntries))

        elif event_type == "ws_connect":
            adp = get_adapter()
            path = event_data["path"]

            # Clean path if it has scheme/host/port prefix
            if "://" in path:
                from urllib.parse import urlparse
                path = urlparse(path).path
            elif path.startswith(":"):
                slash_idx = path.find("/")
                if slash_idx != -1:
                    path = path[slash_idx:]

            # Tear down any prior connection on the same adapter so its
            # WebSocketRouter handler exits cleanly (cancels the framework's
            # _ping_loop). Without this, the orphan ping loop fires after the
            # client has moved on and logs "WebSocket ping timeout".
            for _t in list(getattr(handle_js_message, "_ws_tasks", [])):
                _t.cancel()
            handle_js_message._ws_tasks = []
            for _cid in list(getattr(handle_js_message, "_id_map", {}).values()):
                try:
                    await adp.ws_close(_cid)
                except Exception:
                    pass
            handle_js_message._id_map = {}

            connection_id = await adp.ws_connect(path=path)
            handle_js_message._id_map[req_id] = connection_id

            # Send the websocket.accept message to JS so MockWebSocket transitions to OPEN
            # (ws_connect() consumes the accept internally — we must forward it explicitly)
            accept_payload = {
                "type": "ws_message",
                "id": req_id,
                "message": {"type": "websocket.accept"},
            }
            js.postMessage(
                to_js(accept_payload, dict_converter=js.Object.fromEntries)
            )

            # Start forwarding outgoing WS messages to JS
            async def forward_ws_messages():
                try:
                    while True:
                        msg = await adp.ws_receive(connection_id)
                        # Convert bytes to list for JS transfer
                        if "bytes" in msg and isinstance(msg["bytes"], bytes):
                            msg["bytes"] = list(msg["bytes"])
                        if "text" in msg and isinstance(msg["text"], bytes):
                            msg["text"] = msg["text"].decode("utf-8")
                        payload = {"type": "ws_message", "id": req_id, "message": msg}
                        js.postMessage(
                            to_js(payload, dict_converter=js.Object.fromEntries)
                        )
                        if msg.get("type") == "websocket.close":
                            break
                except Exception as e:
                    print(f"WS forward error: {e}")

            fwd_task = asyncio.create_task(forward_ws_messages())
            handle_js_message._ws_tasks = [fwd_task]

        elif event_type == "ws_send":
            adp = get_adapter()
            id_map = getattr(handle_js_message, "_id_map", {})
            connection_id = id_map.get(req_id)
            if connection_id:
                data = event_data["data"]
                if isinstance(data, list):
                    data = bytes(data)
                    # Rewrite tutorial paths
                    try:
                        import msgpack
                        payload = msgpack.unpackb(data)
                        if isinstance(payload, dict) and "path" in payload:
                            if payload["path"].startswith("/docs/"):
                                payload["path"] = "/"
                                data = msgpack.packb(payload)
                    except Exception:
                        pass
                    await adp.ws_send(connection_id, data)
                else:
                    await adp.ws_send_text(connection_id, data)

    except Exception as e:
        print(f"CRITICAL ERROR in handle_js_message: {e}")
        traceback.print_exc()


# Expose to JS
import js  # noqa: E402

js.handle_message = handle_js_message


def reload_page(path_str):
    import pathlib

    try:
        app = get_adapter().app
        path = pathlib.Path(path_str)
        app.reload_page(path)
        return True
    except Exception as e:
        print(f"Reload failed for {path_str}: {e}")
        traceback.print_exc()
        return False


js.reload_page = reload_page


def restart_server(pages_dir="/app"):
    global app_instance, adapter, current_pages_dir
    print(f"restart_server called with pages_dir={pages_dir}")

    # Cancel forwarder tasks and disconnect open WS connections on the old
    # adapter. The disconnect runs the framework's WebSocketRouter cleanup
    # (cancels its _ping_loop), preventing "WebSocket ping timeout" warnings
    # from the dead connection after restart.
    for _t in list(getattr(handle_js_message, "_ws_tasks", [])):
        _t.cancel()
    handle_js_message._ws_tasks = []
    old_adapter = adapter
    old_ids = list(getattr(handle_js_message, "_id_map", {}).values())
    handle_js_message._id_map = {}
    if old_adapter is not None and old_ids:
        async def _drain_old_ws():
            for _cid in old_ids:
                try:
                    await old_adapter.ws_close(_cid)
                except Exception:
                    pass
        asyncio.create_task(_drain_old_ws())

    app_instance = None
    adapter = None
    current_pages_dir = pages_dir
    try:
        from pywire.runtime.loader import get_loader
        get_loader().invalidate_cache()
    except Exception as e:
        print(f"Failed to invalidate loader cache: {e}")


js.restart_server = restart_server
