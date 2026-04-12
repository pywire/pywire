"""WebSocket handler for PyWire."""

import asyncio
import inspect
import sys
import traceback
import uuid
from typing import Any, Dict, Set, cast

import msgpack
from starlette.responses import Response
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

        try:
            # Create isolated page instance for this connection
            # We need to reconstruct the page based on current URL
            # Note: This simplifies things by assuming initial state.
            # Real session support would hydrate state here.

            # Since we don't have the request context easily here yet without
            # more complex routing, we wait for the first event to associate/create
            # the page if needed, or we rely on the client to send initial context.
            # For this MVP, we'll instantiate the page when an event arrives.

            while True:
                data_bytes = await websocket.receive_bytes()
                data = msgpack.unpackb(data_bytes, raw=False)
                await self._process_message(websocket, data)

        except WebSocketDisconnect:
            self.active_connections.remove(websocket)
            if websocket in self.connection_pages:
                del self.connection_pages[websocket]
            # Keep session in store (TTL handles cleanup) — enables reconnect
            self.session_ids.pop(websocket, None)
        except asyncio.CancelledError:
            # Server shutdown, clean disconnect
            self.active_connections.discard(websocket)
            if websocket in self.connection_pages:
                del self.connection_pages[websocket]
            self.session_ids.pop(websocket, None)
            # Don't re-raise, let it exit gracefully
            return
        except Exception as e:
            print(f"WebSocket error: {e}")
            import traceback

            traceback.print_exc()

    async def _process_message(
        self, websocket: WebSocket, data: Dict[str, Any]
    ) -> None:
        """Process incoming message from client."""
        msg_type = data.get("type")

        if msg_type == "event":
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
        if isinstance(update, Response):
            html = cast(bytes, update.body).decode("utf-8")
            await websocket.send_bytes(msgpack.packb({"type": "update", "html": html}))
            return

        if isinstance(update, dict):
            if update.get("type") == "regions":
                payload = {"type": "update", "regions": update.get("regions", [])}
                if "commands" in update:
                    payload["commands"] = update["commands"]
                await websocket.send_bytes(msgpack.packb(payload))
                return
            if update.get("type") == "full":
                html = update.get("html", "")
                payload = {"type": "update", "html": html}
                if "commands" in update:
                    payload["commands"] = update["commands"]
                await websocket.send_bytes(msgpack.packb(payload))
                return

        # Fallback: force full reload
        await websocket.send_bytes(msgpack.packb({"type": "reload"}))

    async def _handle_init(self, websocket: WebSocket, data: Dict[str, Any]) -> None:
        """Handle initial page load."""
        path = data.get("path", "/")

        # Define callback for log streaming
        async def send_log(msg: str, level: str = "info") -> None:
            if msg and msg.strip():
                await self._send_console_message(websocket, output=msg, level=level)

        token = log_callback_ctx.set(send_log)

        try:
            # Logic similar to _handle_relocate to create page
            from urllib.parse import parse_qs, urlparse
            from starlette.requests import Request

            parsed_url = urlparse(path)
            pathname = parsed_url.path
            query_string = parsed_url.query

            match = self.app.router.match(pathname)
            if not match:
                print(f"Init: No route found for path: {pathname}")
                # 404 behavior? Just return error
                await websocket.send_bytes(
                    msgpack.packb({"type": "error", "error": "Not Found"})
                )
                return

            page_class, params, variant_name = match

            # Create request
            scope = dict(websocket.scope)
            scope["type"] = "http"
            scope["path"] = pathname
            scope["raw_path"] = pathname.encode("ascii")
            scope["query_string"] = (
                query_string.encode("ascii") if query_string else b""
            )
            # Ensure minimal requirements for valid Request
            if "headers" not in scope:
                scope["headers"] = [(b"host", b"localhost")]
            if "method" not in scope:
                scope["method"] = "GET"
            if "scheme" not in scope:
                scope["scheme"] = "http"
            if "server" not in scope:
                scope["server"] = ("localhost", 80)
            if "client" not in scope:
                scope["client"] = ("127.0.0.1", 0)

            request = Request(scope)

            # Parse query params

            if query_string:
                parsed = parse_qs(query_string)
                query = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
            else:
                query = {}

            # Build path info
            path_info = {}
            if hasattr(page_class, "__routes__"):
                for name in page_class.__routes__.keys():
                    path_info[name] = name == variant_name
            elif hasattr(page_class, "__route__"):
                path_info["main"] = True

            from pywire.runtime.router import URLHelper

            url_helper = None
            if hasattr(page_class, "__routes__") and page_class.__routes__:
                url_helper = URLHelper(page_class.__routes__)

            # Instantiate page
            page = page_class(
                request=request,
                params=params,
                query=query,
                path=path_info,
                url=url_helper,
            )

            # Session ID: reuse from reconnect or generate new
            client_session_id = data.get("session_id")
            session_id = None

            if client_session_id:
                # Attempt to restore session state from store
                try:
                    snapshot = await self.app.session_store.get(client_session_id)
                    if snapshot:
                        restore_page_state(page, snapshot)
                        session_id = client_session_id
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

            # Send ack with session ID
            await websocket.send_bytes(
                msgpack.packb({"type": "init_ack", "session_id": session_id})
            )

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
                # Find page stuff (logic copied from existing)
                # ...
                # Actually, duplicate logic from _handle_relocate is risky.
                # Do we need to recreate page here?
                # The original code did have logic to CREATE page if missing.
                # Let's verify if I can just use self.connection_pages[websocket]
                # If it's not there, maybe we should return or error?
                # Original code checked `if websocket not in self.connection_pages`
                # at start of try block.

                # Re-implementing logic from reading Step 777 (which showed start of try)
                # lines 116-179 in Step 777.
                # I should just reference specific logic.
                from urllib.parse import parse_qs, urlparse

                # Create minimal request-like object if needed, or update Page
                # to accept None/minimal context for WS mode
                # For now, we'll pass a mock request or the websocket itself if Page supports it
                from starlette.requests import Request

                from pywire.runtime.router import URLHelper

                parsed_url = urlparse(path)
                pathname = parsed_url.path
                query_string = parsed_url.query

                match = self.app.router.match(pathname)
                if not match:
                    print(f"No route found for path: {pathname}")
                    return

                page_class, params, variant_name = match

                # Construct a mock request from the websocket scope
                # This is a simplification; ideally Page accepts WebSocket or Request
                # Construct a mock request with the correct page path
                # We copy scope to avoid mutating the actual WebSocket scope
                scope = dict(websocket.scope)
                scope["type"] = "http"
                scope["path"] = pathname
                scope["raw_path"] = pathname.encode("ascii")
                scope["query_string"] = (
                    query_string.encode("ascii") if query_string else b""
                )
                # Ensure minimal requirements for valid Request
                if "headers" not in scope:
                    scope["headers"] = [(b"host", b"localhost")]
                if "method" not in scope:
                    scope["method"] = "GET"
                if "scheme" not in scope:
                    scope["scheme"] = "http"
                if "server" not in scope:
                    scope["server"] = ("localhost", 80)
                if "client" not in scope:
                    scope["client"] = ("127.0.0.1", 0)

                request = Request(scope)

                if query_string:
                    parsed = parse_qs(query_string)
                    query = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
                else:
                    query = {}

                path_info = {}
                if hasattr(page_class, "__routes__"):
                    for name in page_class.__routes__.keys():
                        path_info[name] = name == variant_name

                url_helper = None
                if hasattr(page_class, "__routes__"):
                    url_helper = URLHelper(page_class.__routes__)

                page = page_class(
                    request, params, query, path=path_info, url=url_helper
                )
                if hasattr(self.app, "get_user"):
                    page.user = self.app.get_user(websocket)

                self.connection_pages[websocket] = page

                # Force initial render to establish wire tracking
                # This ensures _track_read is called and regions are registered
                # so that subsequent writes in handlers trigger updates
                await page.render(init=True)

                if hasattr(page, "on_load"):
                    if inspect.iscoroutinefunction(page.on_load):
                        await page.on_load()
                    else:
                        page.on_load()
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

            # Get existing page instance
            page = self.connection_pages.get(websocket)
            if not page:
                # No page instance yet - create one for this path
                # This happens when user navigates via SPA link before any @click
                from urllib.parse import parse_qs, urlparse

                from starlette.requests import Request

                from pywire.runtime.router import URLHelper

                parsed_url = urlparse(path)
                pathname = parsed_url.path
                query_string = parsed_url.query

                match = self.app.router.match(pathname)
                if not match:
                    print(f"Relocate: No route found for path: {pathname}")
                    # Command client to perform a full reload (which will hit the server and 404)
                    await websocket.send_bytes(msgpack.packb({"type": "reload"}))
                    return

                page_class, params, variant_name = match

                # Create request with correct path
                scope = dict(websocket.scope)
                scope["type"] = "http"
                scope["path"] = pathname
                scope["raw_path"] = pathname.encode("ascii")
                scope["query_string"] = (
                    query_string.encode("ascii") if query_string else b""
                )
                # Ensure minimal requirements for valid Request
                if "headers" not in scope:
                    scope["headers"] = [(b"host", b"localhost")]
                if "method" not in scope:
                    scope["method"] = "GET"
                if "scheme" not in scope:
                    scope["scheme"] = "http"
                if "server" not in scope:
                    scope["server"] = ("localhost", 80)
                if "client" not in scope:
                    scope["client"] = ("127.0.0.1", 0)
                request = Request(scope)

                # Parse query
                if query_string:
                    parsed = parse_qs(query_string)
                    query = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
                else:
                    query = {}

                # Build path info
                path_info = {}
                routes = getattr(page_class, "__routes__", {})
                if routes:
                    for name in routes.keys():
                        path_info[name] = name == variant_name
                elif hasattr(page_class, "__route__"):
                    path_info["main"] = True

                # Build URL helper
                url_helper = None
                if routes:
                    url_helper = URLHelper(cast(dict[str, str], routes))

                # Create page instance
                page = page_class(
                    request, params, query, path=path_info, url=url_helper
                )

                # Populate user if hook exists
                if hasattr(self.app, "get_user"):
                    page.user = self.app.get_user(websocket)

                self.connection_pages[websocket] = page

                # Set update hook
                async def broadcast_update() -> None:
                    update = await page.render_update(init=False)
                    await self._send_update_payload(websocket, update)

                page._on_update = broadcast_update

                # Run on_load lifecycle hook
                if hasattr(page, "on_load"):
                    if inspect.iscoroutinefunction(page.on_load):
                        await page.on_load()
                    else:
                        page.on_load()

                # Render and send body-only HTML (init=False avoids re-injecting client scripts)
                response = await page.render(init=False)
                html = cast(bytes, response.body).decode("utf-8")
                await websocket.send_bytes(
                    msgpack.packb({"type": "update", "html": html})
                )
                return

            # Parse new URL
            from urllib.parse import parse_qs, urlparse

            parsed_url = urlparse(path)
            pathname = parsed_url.path
            query_string = parsed_url.query

            # Match route to get new params and variant
            match = self.app.router.match(pathname)
            if not match:
                # Try custom 404 route
                # This keeps the SPA alive instead of reloading
                match = self.app.router.match("/404")

                if match:
                    print(f"Relocate: Route not found for {pathname}, serving /404")
                else:
                    # Try /__error__ fallback
                    match = self.app.router.match("/__error__")

                    if match:
                        print(
                            f"Relocate: Route not found for {pathname}, serving /__error__"
                        )
                    else:
                        # Fallback to generic ErrorPage if no custom 404
                        # We need to construct a bound ErrorPage class
                        print(
                            f"Relocate: Route not found for {pathname}, serving generic 404"
                        )
                        from pywire.runtime.error_page import ErrorPage

                        # Create a closure helper
                        class BoundErrorPage(ErrorPage):
                            def __init__(
                                self, request: Any, *args: Any, **kwargs: Any
                            ) -> None:
                                super().__init__(
                                    request,
                                    "404 Not Found",
                                    f"The path '{pathname}' could not be found.",
                                )

                        match = (BoundErrorPage, {}, "main")

            page_class, params, variant_name = match

            # Reset page

            if hasattr(page_class, "__routes__"):
                pass

            # print(f"Relocate: Loading page {page_class.__name__} for {pathname}")

            # Create request object
            from starlette.requests import Request

            scope = dict(websocket.scope)
            scope["type"] = "http"
            scope["path"] = pathname
            scope["raw_path"] = pathname.encode("ascii")
            scope["query_string"] = (
                query_string.encode("ascii") if query_string else b""
            )
            # Ensure minimal requirements for valid Request
            if "headers" not in scope:
                scope["headers"] = [(b"host", b"localhost")]
            if "method" not in scope:
                scope["method"] = "GET"
            if "scheme" not in scope:
                scope["scheme"] = "http"
            if "server" not in scope:
                scope["server"] = ("localhost", 80)
            if "client" not in scope:
                scope["client"] = ("127.0.0.1", 0)
            request = Request(scope)

            # Parse query
            if query_string:
                parsed = parse_qs(query_string)
                query = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
            else:
                query = {}

            # Build path info
            path_info = {}
            if hasattr(page_class, "__routes__"):
                for name in page_class.__routes__.keys():
                    path_info[name] = name == variant_name

            # Build URL helper
            from pywire.runtime.router import URLHelper

            url_helper = None
            if hasattr(page_class, "__routes__"):
                url_helper = URLHelper(page_class.__routes__)

            # Instantiate new page
            new_page = page_class(
                request, params, query, path=path_info, url=url_helper
            )

            # If this is an error page (match failed originally), inject error code
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

            # Run __on_load lifecycle hook
            try:
                if hasattr(new_page, "on_load"):
                    if inspect.iscoroutinefunction(new_page.on_load):
                        await new_page.on_load()
                    else:
                        cast(Any, new_page).on_load()

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

                        # Update our reference
                        self.connection_pages[connection] = new_page

                        # Set update hook (needed for background tasks / await blocks)
                        ws = connection

                        async def broadcast_update(
                            _page: Any = new_page, _ws: Any = ws
                        ) -> None:
                            update = await _page.render_update(init=False)
                            await self._send_update_payload(_ws, update)

                        new_page._on_update = broadcast_update

                        # Run on_load lifecycle hook (render with init=False skips it)
                        if hasattr(new_page, "on_load"):
                            if inspect.iscoroutinefunction(new_page.on_load):
                                await new_page.on_load()
                            else:
                                new_page.on_load()

                        # Render with new code but preserved state (init=False avoids re-injecting client scripts)
                        response = await new_page.render(init=False)
                        html = cast(bytes, response.body).decode("utf-8")
                        await connection.send_bytes(
                            msgpack.packb({"type": "update", "html": html})
                        )
                        logger.info(
                            "Hot reload (state preserved) for %s",
                            type(new_page).__name__,
                        )

                    except Exception as e:
                        # Anything failed, fall back to hard reload
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
