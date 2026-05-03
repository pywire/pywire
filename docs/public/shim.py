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
            # ws_ping_interval=0 disables the framework's per-connection
            # _ping_loop. Both ends of this WebSocket live in the same
            # browser tab (iframe ↔ Pyodide worker via postMessage); there
            # is no network to monitor. Under load (e.g. validate() firing
            # many fetchRouteContent → http_request through the worker
            # serially), the pong from the iframe queues up behind the
            # http_requests and misses the 10s pong-deadline → the
            # framework forcibly closes a perfectly healthy connection
            # and triggers a reconnect storm.
            app_instance = PyWire(
                pages_dir=current_pages_dir, debug=True, ws_ping_interval=0
            )
            app_instance._is_dev_mode = True
            adapter = PyodideASGIAdapter(app_instance)
            print("PyWire app initialized successfully")
        except Exception as e:
            print(f"Failed to initialize PyWire app: {repr(e)}")
            traceback.print_exc()
            raise
    return adapter


def _hard_disconnect(adp, connection_id):
    """Force the framework's WebSocketRouter cleanup to actually run.

    `adp.ws_close()` only signals the receive_queue; it does NOT cancel
    the per-connection `_ping_loop` task that PyWire spawns inside
    WebSocketRouter. That task lives on the framework side, sleeps for
    25s, sends a ping, sleeps 10s waiting for a pong — and if the iframe
    document was already replaced, no pong arrives, so the ping_loop
    logs "WebSocket ping timeout, closing connection" and forcibly
    closes the (already-orphaned) ASGI socket. Each iframe replace
    leaves another ping_loop running in the background; eventually one
    fires its timeout and triggers the visible reconnect storm.

    Putting `websocket.disconnect` directly into the receive queue lets
    the framework's own receive() inside _ping_loop wake up, see the
    disconnect, and exit cleanly. We also pop both queues so the
    connection's state is fully gone before the next ws_connect.
    """
    try:
        q = adp._ws_connections.get(connection_id)
        if q is not None:
            q.put_nowait({"type": "websocket.disconnect", "code": 1000})
        adp._ws_connections.pop(connection_id, None)
        adp._ws_connections.pop(f"{connection_id}_send", None)
    except Exception as e:
        print(f"_hard_disconnect failed for {connection_id}: {e}")


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

            # Tear down ANY prior server-side WS state for this req_id
            # before standing up a new one. Each iframe doc.write spawns
            # a new MockWebSocket → new ws_connect with the same
            # req_id="ws-main", but the previous forwarder task is still
            # awaiting `send_queue.get()` (ws_close only puts a sentinel
            # in receive_queue, not send_queue, so the forwarder stays
            # blocked indefinitely). Forwarder tasks accumulate and each
            # one re-broadcasts every server message back to the same
            # req_id, which is why the iframe was seeing N copies of
            # `websocket.accept` and `Application ready` after N cycles.
            #
            # We track forwarders by req_id so we can cancel the prior
            # task explicitly. Cancellation interrupts the get() and the
            # task's `except` swallows the CancelledError cleanly.
            fwd_tasks = getattr(handle_js_message, "_fwd_tasks", None) or {}
            prior_fwd = fwd_tasks.pop(req_id, None)
            if prior_fwd is not None and not prior_fwd.done():
                prior_fwd.cancel()

            id_map = getattr(handle_js_message, "_id_map", {}) or {}
            prior_cid = id_map.pop(req_id, None)
            if prior_cid is not None:
                _hard_disconnect(adp, prior_cid)

            connection_id = await adp.ws_connect(path=path)
            id_map[req_id] = connection_id
            handle_js_message._id_map = id_map

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
                except asyncio.CancelledError:
                    # Expected on doc.write/refresh — the next ws_connect
                    # cancelled us. Don't log; it's the steady state.
                    return
                except Exception as e:
                    print(f"WS forward error: {e}")

            fwd_task = asyncio.create_task(forward_ws_messages())
            fwd_tasks[req_id] = fwd_task
            handle_js_message._fwd_tasks = fwd_tasks
            # Keep _ws_tasks for back-compat with restart_server.
            handle_js_message._ws_tasks = list(fwd_tasks.values())

        elif event_type == "ws_disconnect":
            # Iframe's MockWebSocket told us its close() ran (typically
            # because the parent is about to doc.write a fresh document).
            # Tear down the server-side ASGI WebSocket so its ping_loop
            # is cancelled and we don't accumulate zombie connections.
            adp = get_adapter()
            id_map = getattr(handle_js_message, "_id_map", {}) or {}
            connection_id = id_map.pop(req_id, None)
            handle_js_message._id_map = id_map
            if connection_id:
                _hard_disconnect(adp, connection_id)
            fwd_tasks = getattr(handle_js_message, "_fwd_tasks", None) or {}
            fwd_task = fwd_tasks.pop(req_id, None)
            if fwd_task is not None and not fwd_task.done():
                fwd_task.cancel()
            handle_js_message._fwd_tasks = fwd_tasks
            handle_js_message._ws_tasks = list(fwd_tasks.values())

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
    """Invalidate a single page's cached compile output.

    The worker calls this after every UPDATE_FILE. After restart_server,
    files arrive sequentially (pages first, then components). We must NOT
    eagerly construct the adapter here — PyWire(__init__) calls
    _load_pages() which compiles every .wire it finds, executing top-level
    imports like `from components.badge import Badge`. If components/
    hasn't been written yet, that import raises ModuleNotFoundError and
    the page is registered as a permanent error page.

    Skip when the adapter doesn't exist; the next http_request will
    construct it fresh, by which time the worker has finished writing
    every UPDATE_FILE for this step.
    """
    if adapter is None:
        return True

    import pathlib

    try:
        path = pathlib.Path(path_str)
        adapter.app.reload_page(path)
        return True
    except Exception as e:
        print(f"Reload failed for {path_str}: {e}")
        traceback.print_exc()
        return False


js.reload_page = reload_page


def delete_file(path_str):
    """Delete a file from the virtual FS and drop it from the loader cache.

    Mirrors reload_page's lazy semantics: if the adapter doesn't exist yet,
    we still remove the file from disk but skip the loader call.
    """
    import os
    import pathlib

    try:
        if os.path.exists(path_str):
            os.remove(path_str)
        if adapter is not None:
            try:
                adapter.app.reload_page(pathlib.Path(path_str))
            except Exception:
                # File no longer exists — loader will drop it on next access
                pass
        return True
    except Exception as e:
        print(f"delete_file failed for {path_str}: {e}")
        traceback.print_exc()
        return False


js.delete_file = delete_file


def sync_pages(pages_dir, files):
    """Atomic file-set sync: write `files`, delete anything else under pages_dir.

    `files` is a JS object {relpath: content}. Paths are written under /app/.
    Files under pages_dir but not in `files` are deleted. After all FS edits,
    we invalidate the loader cache for each touched path so next request
    sees fresh source.
    """
    global current_pages_dir
    import os
    import pathlib

    try:
        # Convert JS object → dict if needed
        if hasattr(files, "to_py"):
            files_dict = files.to_py()
        else:
            files_dict = dict(files)

        # Resolve pages_dir to absolute /app/...
        if pages_dir and not pages_dir.startswith("/"):
            abs_pages_dir = f"/app/{pages_dir}"
        else:
            abs_pages_dir = pages_dir or "/app"
        current_pages_dir = abs_pages_dir

        # Compute target absolute paths for all incoming files
        target_paths = set()
        for rel, content in files_dict.items():
            abs_path = f"/app/{rel}"
            target_paths.add(os.path.normpath(abs_path))
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w") as f:
                f.write(content)

        # Delete anything under pages_dir not in target_paths
        if os.path.exists(abs_pages_dir):
            for root, _dirs, fnames in os.walk(abs_pages_dir):
                for fname in fnames:
                    full = os.path.normpath(os.path.join(root, fname))
                    if full not in target_paths:
                        try:
                            os.remove(full)
                        except Exception:
                            pass

        # Invalidate loader cache for each touched file (and anything we deleted).
        # If adapter not built yet, skip — next request builds fresh.
        if adapter is not None:
            for p in target_paths:
                try:
                    adapter.app.reload_page(pathlib.Path(p))
                except Exception:
                    pass
            # Mirror native `pywire dev` HMR: broadcast a state-preserving
            # reload to active WS clients so the iframe re-renders against
            # the updated code without losing component/page state. Without
            # this, edits only show up after a full navigation/refresh.
            try:
                ws_handler = getattr(adapter.app, "ws_handler", None)
                if ws_handler is not None:
                    asyncio.ensure_future(ws_handler.broadcast_reload())
            except Exception as e:
                print(f"broadcast_reload failed: {e}")
        return True
    except Exception as e:
        print(f"sync_pages failed: {e}")
        traceback.print_exc()
        return False


js.sync_pages = sync_pages


def restart_server(pages_dir="/app"):
    global app_instance, adapter, current_pages_dir
    print(f"restart_server called with pages_dir={pages_dir}")

    # Cancel forwarder tasks and disconnect open WS connections on the old
    # adapter. The disconnect runs the framework's WebSocketRouter cleanup
    # (cancels its _ping_loop), preventing "WebSocket ping timeout" warnings
    # and orphaned ping loops from accumulating after each step nav.
    #
    # ws_close is async-typed but contains no awaits — its body is just sync
    # queue.put_nowait + dict.pop. Inline those operations directly so the
    # disconnect lands deterministically before this function returns.
    # (Wrapping in asyncio.create_task without saving the reference risks
    # the task being GC'd before it runs.)
    for _t in list(getattr(handle_js_message, "_ws_tasks", [])):
        _t.cancel()
    handle_js_message._ws_tasks = []
    handle_js_message._fwd_tasks = {}
    old_adapter = adapter
    old_ids = list(getattr(handle_js_message, "_id_map", {}).values())
    handle_js_message._id_map = {}
    if old_adapter is not None:
        for _cid in old_ids:
            try:
                _q = old_adapter._ws_connections.get(_cid)
                if _q is not None:
                    _q.put_nowait({"type": "websocket.disconnect", "code": 1000})
                old_adapter._ws_connections.pop(_cid, None)
                old_adapter._ws_connections.pop(f"{_cid}_send", None)
            except Exception:
                pass

    app_instance = None
    adapter = None
    current_pages_dir = pages_dir
    try:
        from pywire.runtime.loader import get_loader
        get_loader().invalidate_cache()
    except Exception as e:
        print(f"Failed to invalidate loader cache: {e}")


js.restart_server = restart_server
