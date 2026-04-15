"""WebSocket handler for PyWire."""

import asyncio
import re
import sys
import traceback
import uuid
from typing import Any, Dict, Set, cast

import msgpack
from starlette.websockets import WebSocket, WebSocketDisconnect

import logging
from pywire.runtime.logging import log_callback_ctx
from pywire.runtime.page import BasePage
from pywire.runtime.session_serializer import restore_page_state, snapshot_page_state
from pywire import __version__

logger = logging.getLogger(__name__)


class WebSocketHandler:
    """Handles WebSocket connections for events and hot reload."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.active_connections: Set[WebSocket] = set()
        # Map websocket to page instance
        self.connection_pages: Dict[WebSocket, BasePage] = {}
        # Map websocket to session ID for state persistence
        self.session_ids: Dict[WebSocket, str] = {}
        # Map websocket to its ping loop task
        self._ping_tasks: Dict[WebSocket, asyncio.Task[None]] = {}
        # Track pending pong events per connection
        self._pong_events: Dict[WebSocket, asyncio.Event] = {}

    async def handle(self, websocket: WebSocket) -> None:
        """Handle new WebSocket connection."""
        # Optional: Auth check hook
        if hasattr(self.app, "on_ws_connect"):
            if not await self.app.on_ws_connect(websocket):
                await websocket.close()
                return

        await websocket.accept()
        self.active_connections.add(websocket)

        # Send init message
        await websocket.send_bytes(
            msgpack.packb({"type": "init", "version": __version__})
        )

        # Start keep-alive ping loop
        ping_interval = getattr(self.app, "ws_ping_interval", 25)
        if ping_interval > 0:
            self._pong_events[websocket] = asyncio.Event()
            self._ping_tasks[websocket] = asyncio.create_task(
                self._ping_loop(websocket)
            )

        try:
            while True:
                data_bytes = await websocket.receive_bytes()
                data = msgpack.unpackb(data_bytes, raw=False)
                await self._process_message(websocket, data)

        except WebSocketDisconnect:
            pass
        except asyncio.CancelledError:
            # Server shutdown, clean disconnect — don't re-raise
            pass
        except Exception as e:
            print(f"WebSocket error: {e}")
            traceback.print_exc()
        finally:
            self._cleanup_connection(websocket)

    def _cleanup_connection(self, websocket: WebSocket) -> None:
        """Clean up all state associated with a WebSocket connection."""
        # Cancel ping task
        task = self._ping_tasks.pop(websocket, None)
        if task and not task.done():
            task.cancel()
        self._pong_events.pop(websocket, None)

        self.active_connections.discard(websocket)
        self.connection_pages.pop(websocket, None)
        # Keep session in store (TTL handles cleanup) — enables reconnect
        self.session_ids.pop(websocket, None)

    async def _ping_loop(self, websocket: WebSocket) -> None:
        """Send periodic pings and close the connection if pong is not received."""
        interval: int = getattr(self.app, "ws_ping_interval", 25)
        timeout: int = getattr(self.app, "ws_ping_timeout", 10)
        pong_event = self._pong_events[websocket]

        try:
            while True:
                await asyncio.sleep(interval)

                # Send ping
                pong_event.clear()
                try:
                    await websocket.send_bytes(msgpack.packb({"type": "ping"}))
                except Exception:
                    # Connection already closed
                    return

                # Wait for pong
                try:
                    await asyncio.wait_for(pong_event.wait(), timeout=timeout)
                except TimeoutError:
                    logger.warning("WebSocket ping timeout, closing connection")
                    try:
                        await websocket.close(code=1000)
                    except Exception:
                        pass
                    return
        except asyncio.CancelledError:
            return

    async def _process_message(
        self, websocket: WebSocket, data: Dict[str, Any]
    ) -> None:
        """Process incoming message from client."""
        msg_type = data.get("type")

        if msg_type == "pong":
            pong_event = self._pong_events.get(websocket)
            if pong_event:
                pong_event.set()
            return
        elif msg_type == "event":
            await self._handle_event(websocket, data)
        elif msg_type == "init":
            await self._handle_init(websocket, data)
        elif msg_type == "relocate":
            await self._handle_relocate(websocket, data)
        elif msg_type == "ref_sync":
            await self._handle_ref_sync(websocket, data)
        else:
            print(f"Unknown message type: {msg_type}")
            await self._send_console_message(
                websocket, f"Unknown message type: {msg_type}", level="error"
            )

    async def _send_console_message(
        self, websocket: WebSocket, output: str, level: str = "info"
    ) -> None:
        """Send a console log message to the client."""
        # Split by newlines to send as list
        lines = output.splitlines()
        if not lines:
            return

        await websocket.send_bytes(
            msgpack.packb({"type": "console", "lines": lines, "level": level})
        )

    async def _send_error_trace(self, websocket: WebSocket, error: Exception) -> None:
        """Send a structured error trace to the client."""
        # Gate on debug mode + dev mode
        # If not in dev mode, send generic error message only
        if not (getattr(self.app, "_is_dev_mode", False)):
            await websocket.send_bytes(
                msgpack.packb(
                    {
                        "type": "error",
                        "error": f"{type(error).__name__}: An error occurred",
                    }
                )
            )
            return

        exc_type, exc_value, exc_traceback = sys.exc_info()
        trace = []
        if exc_traceback:
            # Skip the first frame if it's just the wrapper?
            # traceback.extract_tb returns all frames.
            summary = traceback.extract_tb(exc_traceback)
            current_tb = exc_traceback
            for frame in summary:
                frame_data = {
                    "filename": frame.filename,
                    "lineno": frame.lineno,
                    "name": frame.name,
                    "line": frame.line,
                }

                # Python 3.11+ provides column information
                if hasattr(frame, "colno") and frame.colno is not None:
                    frame_data["colno"] = frame.colno
                if hasattr(frame, "end_colno") and frame.end_colno is not None:
                    frame_data["end_colno"] = frame.end_colno

                # Fallback: Manual extraction from raw traceback frame if colno missing
                if "colno" not in frame_data and current_tb:
                    try:
                        # Verify we are on the same frame (basic check)
                        if current_tb.tb_frame.f_code.co_filename == frame.filename:
                            code = current_tb.tb_frame.f_code
                            if hasattr(code, "co_positions"):
                                # f_lasti is byte offset, instructions are 2 bytes
                                idx = current_tb.tb_frame.f_lasti // 2
                                positions = list(code.co_positions())
                                if idx < len(positions):
                                    line, end_line, col, end_col = positions[idx]
                                    if col is not None:
                                        frame_data["colno"] = col
                                    if end_col is not None:
                                        frame_data["end_colno"] = end_col
                    except Exception:
                        # Silently fail manual extraction
                        pass

                # Advance to next raw frame
                if current_tb:
                    current_tb = (
                        current_tb.tb_next
                    )  # tb_next is Optional[TracebackType]

                trace.append(frame_data)

        await websocket.send_bytes(
            msgpack.packb(
                {
                    "type": "error_trace",
                    "error": f"{type(error).__name__}: {str(error)}",
                    "trace": trace,
                }
            )
        )

    async def _send_update_payload(self, websocket: WebSocket, update: Any) -> None:
        from pywire.runtime.protocol import build_update_payload

        payload = build_update_payload(update)
        await websocket.send_bytes(msgpack.packb(payload))

    async def _handle_init(self, websocket: WebSocket, data: Dict[str, Any]) -> None:
        """Handle initial page load."""
        path = data.get("path", "/")

        # Define callback for log streaming
        async def send_log(msg: str, level: str = "info") -> None:
            if msg and msg.strip():
                await self._send_console_message(websocket, output=msg, level=level)

        token = log_callback_ctx.set(send_log)

        try:
            from pywire.runtime.page_resolver import resolve_page

            result = resolve_page(
                self.app.router, path, base_scope=dict(websocket.scope)
            )
            if not result:
                print(f"Init: No route found for path: {path}")
                await websocket.send_bytes(
                    msgpack.packb({"type": "error", "error": "Not Found"})
                )
                return

            page, _params, _variant_name = result

            # Session ID: reuse from reconnect or generate new
            client_session_id = data.get("session_id")
            session_id = None
            session_restored = False

            if client_session_id:
                # Attempt to restore session state from store
                try:
                    snapshot = await self.app.session_store.get(client_session_id)
                    if snapshot:
                        restore_page_state(page, snapshot)
                        session_id = client_session_id
                        session_restored = True
                        logger.debug("Restored session %s", session_id)
                except Exception:
                    logger.warning(
                        "Failed to restore session %s",
                        client_session_id,
                        exc_info=True,
                    )

            if session_id is None:
                session_id = str(uuid.uuid4())

            self.connection_pages[websocket] = page
            self.session_ids[websocket] = session_id

            # Define update broadcaster for background tasks (like await blocks)
            async def broadcast_update() -> None:
                update = await page.render_update(init=False)
                await self._send_update_payload(websocket, update)

            page._on_update = broadcast_update
            if getattr(self.app, "debug", False):
                logger.debug(
                    f"[{page._instance_id}] Setting _on_update in _handle_init"
                )

            # Render initial state to register dependencies
            if getattr(self.app, "debug", False):
                logger.debug(
                    f"[{page._instance_id}] Calling page.render(init=True) in _handle_init"
                )
            await page.render(init=True)
            if getattr(self.app, "debug", False):
                logger.debug(
                    f"[{page._instance_id}] Done with page.render(init=True) in _handle_init"
                )

            # Check for pending navigation
            if page._pending_navigation:
                await websocket.send_bytes(
                    msgpack.packb(
                        {"type": "navigate", "path": page._pending_navigation}
                    )
                )
                page._pending_navigation = None
                return

            # Send ack with session ID and restoration status
            await websocket.send_bytes(
                msgpack.packb(
                    {
                        "type": "init_ack",
                        "session_id": session_id,
                        "session_restored": session_restored,
                    }
                )
            )

            # Run @mount hooks after first render delivered to client
            await page._run_hooks(page.MOUNT_HOOKS)

        except Exception as e:
            import traceback

            traceback.print_exc()
            await self._send_error_trace(websocket, e)
        finally:
            log_callback_ctx.reset(token)

    async def _handle_event(self, websocket: WebSocket, data: Dict[str, Any]) -> None:
        """Handle UI event (click, etc)."""
        handler_name = data.get("handler")
        path = data.get("path", "/")
        event_data = data.get("data", {})

        # Define callback for log streaming
        async def send_log(msg: str, level: str = "info") -> None:
            if msg and msg.strip():
                await self._send_console_message(websocket, output=msg, level=level)

        # Set context for this operation
        token = log_callback_ctx.set(send_log)

        try:
            # Get or create page instance
            if websocket not in self.connection_pages:
                from pywire.runtime.page_resolver import resolve_page

                result = resolve_page(
                    self.app.router, path, base_scope=dict(websocket.scope)
                )
                if not result:
                    print(f"No route found for path: {path}")
                    return

                page, _params, _variant_name = result
                if hasattr(self.app, "get_user"):
                    page.user = self.app.get_user(websocket)

                self.connection_pages[websocket] = page

                # Force initial render to establish wire tracking
                await page.render(init=True)
            else:
                page = self.connection_pages[websocket]

            # Define update broadcaster
            async def broadcast_update() -> None:
                update = await page.render_update(init=False)
                await self._send_update_payload(websocket, update)

            page._on_update = broadcast_update

            # Call handler
            try:
                if handler_name:
                    update = await page.handle_event(
                        cast(str, handler_name), event_data
                    )
                else:
                    update = await page.render_update(init=False)
            except Exception as e:
                raise e

            # Check for pending navigation
            if page._pending_navigation:
                await websocket.send_bytes(
                    msgpack.packb(
                        {"type": "navigate", "path": page._pending_navigation}
                    )
                )
                page._pending_navigation = None
                return

            await self._send_update_payload(websocket, update)

            # Run @after_update hooks after re-render sent to client
            await page._run_hooks(page.AFTER_UPDATE_HOOKS)

            # Persist session state after event
            session_id = self.session_ids.get(websocket)
            if session_id:
                self._persist_session(session_id, page)

        except Exception as e:
            # Send structured trace to client (no print - trace is sufficient)
            import traceback

            traceback.print_exc()
            await self._send_error_trace(websocket, e)
        finally:
            log_callback_ctx.reset(token)

    async def _handle_relocate(
        self, websocket: WebSocket, data: Dict[str, Any]
    ) -> None:
        """Handle SPA navigation between sibling paths."""

        # Define callback for log streaming
        # Define callback for log streaming
        async def send_log(msg: str, level: str = "info") -> None:
            if msg and msg.strip():
                await self._send_console_message(websocket, output=msg, level=level)

        token = log_callback_ctx.set(send_log)

        try:
            path = data.get("path", "/")

            from pywire.runtime.page_resolver import resolve_page

            # Get existing page instance
            page = self.connection_pages.get(websocket)
            if not page:
                # No page instance yet — create one for this path
                result = resolve_page(
                    self.app.router, path, base_scope=dict(websocket.scope)
                )
                if not result:
                    print(f"Relocate: No route found for path: {path}")
                    await websocket.send_bytes(msgpack.packb({"type": "reload"}))
                    return

                page, _params, _variant_name = result

                if hasattr(self.app, "get_user"):
                    page.user = self.app.get_user(websocket)

                self.connection_pages[websocket] = page

                # Set update hook
                async def broadcast_update() -> None:
                    update = await page.render_update(init=False)
                    await self._send_update_payload(websocket, update)

                page._on_update = broadcast_update

                # Render and send body-only HTML (init=False avoids re-injecting client scripts)
                response = await page.render(init=False)
                html = cast(bytes, response.body).decode("utf-8")
                await websocket.send_bytes(
                    msgpack.packb({"type": "update", "html": html})
                )

                await page._run_hooks(page.MOUNT_HOOKS)
                return

            # Navigate to new path — try direct match, then 404 fallbacks
            from urllib.parse import urlparse

            pathname = urlparse(path).path

            result = resolve_page(
                self.app.router, path, base_scope=dict(websocket.scope)
            )
            if not result:
                # Try custom 404 route, then /__error__, then generic ErrorPage
                for fallback_path in ("/404", "/__error__"):
                    result = resolve_page(
                        self.app.router,
                        fallback_path,
                        base_scope=dict(websocket.scope),
                    )
                    if result:
                        print(
                            f"Relocate: Route not found for {pathname}, "
                            f"serving {fallback_path}"
                        )
                        break

                if not result:
                    print(
                        f"Relocate: Route not found for {pathname}, serving generic 404"
                    )
                    from pywire.runtime.error_page import ErrorPage

                    class BoundErrorPage(ErrorPage):
                        def __init__(
                            self, request: Any, *args: Any, **kwargs: Any
                        ) -> None:
                            super().__init__(
                                request,
                                "404 Not Found",
                                f"The path '{pathname}' could not be found.",
                            )

                    result = resolve_page(
                        self.app.router, "/", base_scope=dict(websocket.scope)
                    )
                    # Use the bound error page with a synthetic request
                    from starlette.requests import Request

                    scope = dict(websocket.scope)
                    scope["type"] = "http"
                    scope["path"] = pathname
                    new_page = BoundErrorPage(Request(scope))
                    new_page.error_code = 404
                    new_page.user = getattr(page, "user", None)
                    self.connection_pages[websocket] = new_page

                    async def broadcast_update_err() -> None:
                        update = await new_page.render_update(init=False)
                        await self._send_update_payload(websocket, update)

                    new_page._on_update = broadcast_update_err

                    try:
                        response = await new_page.render(init=False)
                        html = cast(bytes, response.body).decode("utf-8")
                        await websocket.send_bytes(
                            msgpack.packb({"type": "update", "html": html})
                        )
                        await new_page._run_hooks(new_page.MOUNT_HOOKS)
                    except Exception:
                        await websocket.send_bytes(msgpack.packb({"type": "reload"}))
                    return

            new_page, _params, _variant_name = result

            # If this is a 404 fallback, inject error code
            if not self.app.router.match(pathname):
                new_page.error_code = 404

            # Migrate persistent user state
            new_page.user = getattr(page, "user", None)

            # Replace page instance
            self.connection_pages[websocket] = new_page

            # Set update hook
            async def broadcast_update() -> None:
                update = await new_page.render_update(init=False)
                await self._send_update_payload(websocket, update)

            new_page._on_update = broadcast_update

            try:
                # Render and send body-only HTML (init=False avoids re-injecting client scripts)
                response = await new_page.render(init=False)
                html = cast(bytes, response.body).decode("utf-8")

                # Check for pending navigation
                if new_page._pending_navigation:
                    await websocket.send_bytes(
                        msgpack.packb(
                            {"type": "navigate", "path": new_page._pending_navigation}
                        )
                    )
                    new_page._pending_navigation = None
                    return

                await websocket.send_bytes(
                    msgpack.packb({"type": "update", "html": html})
                )

                # Run @mount hooks after first render delivered to client
                await new_page._run_hooks(new_page.MOUNT_HOOKS)

                # Persist session state after navigation
                session_id = self.session_ids.get(websocket)
                if session_id:
                    self._persist_session(session_id, new_page)
            except Exception:
                raise
        except Exception as e:
            # If relocation fails (e.g. 500 error), force a full reload
            # This ensures the browser hits the server and gets the proper error page (or 500 page)
            print(f"Error handling relocate: {e}", file=sys.stderr)
            await websocket.send_bytes(msgpack.packb({"type": "reload"}))
        finally:
            log_callback_ctx.reset(token)

    def _persist_session(self, session_id: str, page: BasePage) -> None:
        """Schedule non-blocking session persistence."""
        asyncio.create_task(self._do_persist_session(session_id, page))

    async def _do_persist_session(self, session_id: str, page: BasePage) -> None:
        """Persist page state to the session store (background)."""
        try:
            snapshot = snapshot_page_state(page, warn_size=self.app.session_warn_size)
            await self.app.session_store.set(
                session_id, snapshot, ttl=self.app.session_ttl
            )
        except Exception:
            logger.warning("Failed to persist session %s", session_id, exc_info=True)

    async def broadcast_shutdown(self) -> None:
        """Notify all connected clients the server is shutting down.

        Sends a server_shutdown message then closes each WebSocket with code
        1001 (Going Away) so clients suppress auto-reconnect before uvicorn
        stops. The 0.1s sleep gives close frames time to flush.
        """
        if not self.active_connections:
            return
        for connection in list(self.active_connections):
            try:
                await connection.send_bytes(msgpack.packb({"type": "server_shutdown"}))
                await connection.close(code=1001)
            except Exception:
                pass
        await asyncio.sleep(0.1)

    async def broadcast_reload(self) -> None:
        """Broadcast reload to all clients, preserving state where possible.

        For each connection with an existing page instance, attempts to:
        1. Create a new page instance from the updated class
        2. Migrate user state from old instance to new instance
        3. Re-render and send 'update' message
        4. Fall back to hard 'reload' if any step fails
        """
        if not self.active_connections:
            return

        disconnected = set()
        for connection in list(self.active_connections):
            try:
                old_page = self.connection_pages.get(connection)
                if old_page:
                    try:
                        # Get the current URL path from the old page's request
                        path = old_page.request.url.path

                        # Find the NEW page class from the router (which was just updated)
                        match = self.app.router.match(path)
                        if not match:
                            raise Exception(f"No route found for {path}")

                        new_page_class, params, variant_name = match

                        # Create new page instance with same context
                        new_page = new_page_class(
                            old_page.request,
                            params,
                            old_page.query,
                            path=old_page.path,
                            url=old_page.url,
                        )

                        # Migrate user state: copy all non-framework attributes
                        # Framework attrs to skip
                        skip_attrs = {
                            "request",
                            "params",
                            "query",
                            "path",
                            "url",
                            "user",
                            "errors",
                            "loading",
                        }
                        for attr, value in old_page.__dict__.items():
                            if attr not in skip_attrs and not attr.startswith("_"):
                                try:
                                    setattr(new_page, attr, value)
                                except AttributeError:
                                    pass  # Read-only or property, skip

                        # Preserve user
                        new_page.user = old_page.user

                        # Preserve component local state by key.
                        component_snapshots: Dict[str, Dict[str, Any]] = {}
                        old_components = getattr(old_page, "_components", {})
                        for comp_key, old_component in old_components.items():
                            snapshot: Dict[str, Any] = {}
                            for attr, value in old_component.__dict__.items():
                                if attr.startswith("_"):
                                    continue
                                if attr in {
                                    "request",
                                    "params",
                                    "query",
                                    "path",
                                    "url",
                                }:
                                    continue
                                snapshot[attr] = value
                            if snapshot:
                                component_snapshots[comp_key] = snapshot
                        if component_snapshots:
                            new_page._component_state_snapshots.update(
                                component_snapshots
                            )

                        # Set update hook (needed for background tasks / await blocks)
                        ws = connection

                        async def broadcast_update(
                            _page: Any = new_page, _ws: Any = ws
                        ) -> None:
                            update = await _page.render_update(init=False)
                            await self._send_update_payload(_ws, update)

                        new_page._on_update = broadcast_update

                        # Render with new code but preserved state (init=False avoids re-injecting client scripts)
                        response = await new_page.render(init=False)
                        html = cast(bytes, response.body).decode("utf-8")
                        logger.debug(
                            "Hot reload update for %s — handler attrs: %s",
                            type(new_page).__name__,
                            re.findall(r'data-on-\w+="([^"]+)"', html),
                        )
                        await connection.send_bytes(
                            msgpack.packb({"type": "update", "html": html})
                        )

                        # Update page reference AFTER sending the new HTML to
                        # the client. This prevents a race where events from
                        # the old DOM dispatch against the new page instance
                        # (which may have different handler names).
                        self.connection_pages[connection] = new_page

                        logger.info(
                            "Hot reload (state preserved) for %s",
                            type(new_page).__name__,
                        )

                    except Exception as e:
                        # Anything failed, fall back to hard reload.
                        # Ensure old page stays in connection_pages so events
                        # using old handler names still work until the client
                        # completes its hard reload.
                        if old_page:
                            self.connection_pages[connection] = old_page
                        logger.warning(
                            "Hot reload failed, falling back to hard reload: %s",
                            e,
                            exc_info=True,
                        )
                        message_bytes = msgpack.packb({"type": "reload"})
                        await connection.send_bytes(message_bytes)
                else:
                    # No page instance, do hard reload
                    await connection.send_bytes(msgpack.packb({"type": "reload"}))
            except Exception:
                disconnected.add(connection)

        for conn in disconnected:
            self.active_connections.discard(conn)
            if conn in self.connection_pages:
                del self.connection_pages[conn]

    async def _handle_ref_sync(
        self, websocket: WebSocket, data: Dict[str, Any]
    ) -> None:
        """Handle ref value synchronization."""
        ref_id = data.get("refId")
        value = data.get("value")
        prop = data.get("property")

        if not ref_id or websocket not in self.connection_pages:
            return

        page = self.connection_pages[websocket]
        ref = page._refs_by_id.get(ref_id)

        if ref:
            try:
                if prop:
                    # Property sync for media/dialog/canvas elements
                    from pywire.core.refs import (
                        MediaElement,
                        DialogElement,
                        CanvasElement,
                    )

                    if isinstance(ref, MediaElement):
                        ref._update_media_state({prop: value})
                    elif isinstance(ref, DialogElement):
                        ref._update_dialog_state({prop: value})
                    elif isinstance(ref, CanvasElement):
                        ref._update_canvas_state({prop: value})
                else:
                    # Update value directly
                    if hasattr(ref, "_update_value"):
                        ref._update_value(value)
            except Exception as e:
                if getattr(self.app, "debug", False):
                    print(f"Ref sync error for {ref_id}: {e}")
