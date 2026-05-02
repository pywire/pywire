"""WebSocket handler for PyWire."""

import asyncio
import inspect
import re
import sys
import traceback
import uuid
from typing import Any, Dict, Optional, Set, cast

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
        # Virtual cookie jar — tracks cookies set during WS session
        # Virtual cookie jar per connection. Value of ``None`` is a
        # tombstone marking a cookie deleted during the session — it masks
        # any handshake baseline value in ``_get_merged_cookies``.
        self._connection_cookies: Dict[WebSocket, Dict[str, Optional[str]]] = {}
        # Per-connection set of cookie keys the server marked ``HttpOnly``.
        # These stay authoritative in the virtual jar because JS can't
        # observe or mutate them from ``document.cookie``. All other keys
        # are reconciled against ``document.cookie`` on each SPA relocate.
        self._connection_httponly: Dict[WebSocket, Set[str]] = {}
        # Per-connection live-auth subscription task — fan-out from the
        # app's AuthChannel pushes update/revoke events into the WS so the
        # page re-renders when the current user's claims change or the
        # session is revoked mid-session.
        self._auth_subs: Dict[WebSocket, asyncio.Task[None]] = {}
        # Tracks whether we've seen the first SPA-relocate cookie reconcile
        # for a connection. Used to infer HttpOnly for baseline cookies
        # absent from document.cookie on the first reconcile only — on
        # subsequent reconciles we trust the client (a user can legitimately
        # clear a non-HttpOnly cookie in JS).
        self._connection_reconciled: Set[WebSocket] = set()

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

    async def _resolve_user(self, websocket: WebSocket) -> Any:
        """Invoke ``app.get_user``, awaiting if it returns a coroutine.

        ``get_user`` is sync by default but ``pywire-auth`` overrides it
        with an async implementation that reads from the session store.
        """
        if not hasattr(self.app, "get_user"):
            return None
        maybe = self.app.get_user(websocket)
        if inspect.isawaitable(maybe):
            maybe = await maybe
        return maybe

    def _subscribe_auth(self, websocket: WebSocket, principal: Any) -> None:
        """Spawn a live-auth listener for the connected principal.

        No-op when:
        - No auth channel is installed on the app
        - Principal is None / anonymous (no user_id to subscribe)
        - A subscription already exists for this connection

        Cancelled automatically when the WS disconnects.
        """
        if websocket in self._auth_subs:
            return
        channel = getattr(self.app, "_auth_channel", None)
        if channel is None:
            return
        user_id = getattr(principal, "user_id", "") if principal else ""
        is_auth = getattr(principal, "is_authenticated", False) if principal else False
        if not is_auth or not user_id:
            return
        self._auth_subs[websocket] = asyncio.create_task(
            self._live_auth_loop(websocket, user_id, channel)
        )

    async def _live_auth_loop(
        self, websocket: WebSocket, user_id: str, channel: Any
    ) -> None:
        """Pump AuthEvents from the channel into the connected page.

        Each event rewrites ``page.user`` in-place and flags the root scope
        dirty so the next ``render_update`` returns a full re-render.
        ``{$auth}`` regions (and any expression reading ``self.user``)
        re-evaluate as a result.
        """
        from pywire.auth import ANONYMOUS

        try:
            async with channel.subscribe(user_id) as subscription:
                async for event in subscription:
                    page = self.connection_pages.get(websocket)
                    if page is None:
                        return
                    kind = getattr(event, "kind", "")
                    if kind == "revoke":
                        page.user = ANONYMOUS
                    elif getattr(event, "principal", None) is not None:
                        page.user = event.principal
                    else:
                        # Only claims provided — rebuild a principal patch on
                        # top of the current one so existing name / user_id
                        # don't get wiped.
                        claims = getattr(event, "claims", None) or []
                        current = getattr(page, "user", None)
                        if current is not None and hasattr(current, "claims"):
                            from dataclasses import replace

                            try:
                                page.user = replace(current, claims=list(claims))
                            except TypeError:
                                pass
                    # If the page has an !auth guard, re-evaluate against
                    # the new principal. A newly-denied page (common after
                    # revoke / role downgrade) emits a navigate so the
                    # client leaves the protected page instead of silently
                    # re-rendering with ANONYMOUS.
                    if getattr(page.__class__, "__auth_required__", False):
                        from pywire.auth.guard import run_auth_guard

                        try:
                            denied = await run_auth_guard(page)
                        except Exception:
                            logger.warning(
                                "live-auth: guard evaluation failed", exc_info=True
                            )
                            denied = None
                        if denied is not None:
                            location = denied.headers.get("location") or "/"
                            try:
                                await websocket.send_bytes(
                                    msgpack.packb(
                                        {"type": "navigate", "path": location}
                                    )
                                )
                            except Exception:
                                logger.debug(
                                    "live-auth: navigate send failed",
                                    exc_info=True,
                                )
                            # Stop pumping — the client will reconnect on
                            # the new path and start a fresh subscription.
                            return

                    # Root-scope invalidation triggers a full re-render on
                    # the next render_update call (see page.render_update).
                    page._dirty_regions.add(None)  # ty: ignore[invalid-argument-type]
                    on_update = getattr(page, "_on_update", None)
                    if on_update is not None:
                        try:
                            await on_update()
                        except Exception:
                            logger.warning(
                                "live-auth: broadcast_update failed", exc_info=True
                            )
        except asyncio.CancelledError:
            return
        except Exception:
            logger.warning("live-auth loop exited with error", exc_info=True)

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
        self._connection_cookies.pop(websocket, None)
        self._connection_httponly.pop(websocket, None)
        self._connection_reconciled.discard(websocket)
        sub_task = self._auth_subs.pop(websocket, None)
        if sub_task and not sub_task.done():
            sub_task.cancel()

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

        # Keep virtual cookie jar in sync with cookie commands sent to client
        commands = payload.get("commands", [])
        if commands:
            self._update_cookie_jar_from_commands(websocket, commands)

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

            # Populate principal on initial page (parity with _handle_event and
            # _handle_relocate — previously missed here so the first render
            # always saw user=None). Only overwrite when resolution yields a
            # real principal; without auth installed, `user` may be a page
            # script variable we must not clobber.
            resolved_user = await self._resolve_user(websocket)
            if resolved_user is not None:
                page.user = resolved_user

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

            # Subscribe to the app's auth channel so revoke / update events
            # trigger a live re-render without requiring a page reload.
            self._subscribe_auth(websocket, resolved_user)

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
                resolved_user = await self._resolve_user(websocket)
                if resolved_user is not None:
                    page.user = resolved_user

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
        """Handle SPA navigation via internal ASGI request replay.

        Instead of directly instantiating the target page, dispatches an
        internal HTTP request through the full ASGI middleware stack. This
        ensures auth, rate limiting, CORS, and other middleware apply to
        SPA navigations just as they do to regular HTTP requests.

        After the internal dispatch, a local page instance is still created
        for ongoing WebSocket state management (event handling, refs, etc.).
        """

        # Define callback for log streaming
        async def send_log(msg: str, level: str = "info") -> None:
            if msg and msg.strip():
                await self._send_console_message(websocket, output=msg, level=level)

        token = log_callback_ctx.set(send_log)

        try:
            path = data.get("path", "/")

            from pywire.runtime.internal_request import dispatch_internal
            from pywire.runtime.page_resolver import resolve_page

            # 0. Reconcile jar against client-reported cookies so browser-side
            #    deletions (document.cookie mutations, devtools clears) take
            #    effect on this relocate instead of waiting for a hard reload.
            client_cookie_header = data.get("cookies")
            if isinstance(client_cookie_header, str):
                self._reconcile_from_client_cookies(websocket, client_cookie_header)

            # 1. Build merged cookies and headers for internal dispatch
            cookies = self._get_merged_cookies(websocket)
            headers = self._build_internal_headers(websocket, cookies)

            # 2. Dispatch through the full ASGI middleware stack
            dispatch_target = self.app._get_dispatch_target()
            response = await dispatch_internal(
                dispatch_target,
                path=path,
                headers=headers,
                base_scope=dict(websocket.scope),
            )

            # 3. Sync cookies from the internal response
            cookie_commands = self._sync_cookies_from_response(
                websocket, response.raw_headers
            )

            # 4. Handle response based on status code
            if 300 <= response.status < 400:
                # Redirect — tell client to navigate to the new location
                location = response.headers.get("location", "/")
                await websocket.send_bytes(
                    msgpack.packb({"type": "navigate", "path": location})
                )
                return

            if response.status >= 400:
                # Error response — send the error page HTML
                html = response.body.decode("utf-8")
                payload: Dict[str, Any] = {"type": "update", "html": html}
                if cookie_commands:
                    payload["commands"] = cookie_commands
                await websocket.send_bytes(msgpack.packb(payload))
                return

            # 5. Success (200) — send body HTML and set up local page instance.
            # Resolve the new page first so we can both attach meta to the
            # response payload AND set it up as the connection's active
            # page below (single resolve_page call, not two).
            old_page = self.connection_pages.get(websocket)
            result = resolve_page(
                self.app.router, path, base_scope=dict(websocket.scope)
            )

            html = response.body.decode("utf-8")
            payload: Dict[str, Any] = {"type": "update", "html": html}
            if cookie_commands:
                payload["commands"] = cookie_commands

            # Include per-page meta so the client can re-evaluate
            # `!no_interactive` after SPA nav. The internal dispatch
            # rendered with init=False so the response body has no
            # `_pywire_spa_meta` script tag — without this, the client
            # carries the previous page's `pageInteractive` value.
            if result:
                payload["meta"] = {
                    "page_interactive": not bool(
                        getattr(result[0], "__no_interactive__", False)
                    ),
                }

            await websocket.send_bytes(msgpack.packb(payload))

            # 6. Continue setting up the local page instance for WS state
            #    management (The internal dispatch already rendered the page
            #    — this instance is for handling subsequent events on the new page.)
            if result:
                new_page, _params, _variant_name = result

                # Migrate persistent user state from old page
                if old_page:
                    new_page.user = getattr(old_page, "user", None)
                else:
                    resolved_user = await self._resolve_user(websocket)
                    if resolved_user is not None:
                        new_page.user = resolved_user

                # Replace page instance for this connection
                self.connection_pages[websocket] = new_page

                # Set update hook for async state changes
                async def broadcast_update() -> None:
                    update = await new_page.render_update(init=False)
                    await self._send_update_payload(websocket, update)

                new_page._on_update = broadcast_update

                # Run @mount hooks
                await new_page._run_hooks(new_page.MOUNT_HOOKS)

                # Prime wire-subscriber tracking on this local instance.
                # The internal dispatch rendered a DIFFERENT page instance
                # to produce the HTML we just sent; this local one is what
                # handles subsequent events. Without a render call here,
                # `register_read` never fires for its wires → no region
                # subscriptions → handler writes invalidate nothing →
                # `render_update` returns empty regions → UI looks frozen.
                try:
                    await new_page.render(init=False)
                except Exception:
                    logger.debug(
                        "relocate: priming render on %s failed",
                        path,
                        exc_info=True,
                    )

                # Persist session state
                session_id = self.session_ids.get(websocket)
                if session_id:
                    self._persist_session(session_id, new_page)

        except Exception as e:
            # If relocation fails, force a full reload so the browser
            # hits the server and gets the proper error page
            print(f"Error handling relocate: {e}", file=sys.stderr)
            await websocket.send_bytes(msgpack.packb({"type": "reload"}))
        finally:
            log_callback_ctx.reset(token)

    # ------------------------------------------------------------------
    # Cookie helpers for internal ASGI replay
    # ------------------------------------------------------------------

    def _get_handshake_cookies(self, websocket: WebSocket) -> dict[str, str]:
        """Parse cookies from the original WebSocket handshake."""
        from pywire.runtime.internal_request import parse_cookie_header

        for name, value in websocket.scope.get("headers", []):
            if name == b"cookie":
                return parse_cookie_header(value.decode("latin-1"))
        return {}

    def _get_merged_cookies(self, websocket: WebSocket) -> dict[str, str]:
        """Merge handshake cookies with any cookies set during the WS session.

        The virtual jar uses ``None`` as a tombstone to mark cookies deleted
        during the session — those keys are removed from the merge so a
        prior handshake value doesn't shadow a middleware-issued logout.
        """
        baseline = self._get_handshake_cookies(websocket)
        virtual = self._connection_cookies.get(websocket, {})
        merged: dict[str, str] = {
            **baseline,
            **{k: v for k, v in virtual.items() if v is not None},
        }
        for key, value in virtual.items():
            if value is None:
                merged.pop(key, None)
        return merged

    def _build_internal_headers(
        self, websocket: WebSocket, cookies: dict[str, str]
    ) -> dict[str, str]:
        """Build HTTP headers for an internal request from WS handshake scope."""
        from pywire.runtime.internal_request import encode_cookie_header

        headers: dict[str, str] = {}

        # Copy relevant headers from the WS handshake
        for name_bytes, value_bytes in websocket.scope.get("headers", []):
            name = name_bytes.decode("latin-1").lower()
            # Skip headers that don't apply to internal HTTP requests
            if name in (
                "connection",
                "upgrade",
                "sec-websocket-key",
                "sec-websocket-version",
                "sec-websocket-extensions",
                "sec-websocket-protocol",
                "cookie",  # replaced with merged cookies below
            ):
                continue
            headers[name] = value_bytes.decode("latin-1")

        # Set merged cookies
        if cookies:
            headers["cookie"] = encode_cookie_header(cookies)

        # Mark as internal relocate request
        headers["x-pywire-internal"] = "relocate"

        return headers

    def _sync_cookies_from_response(
        self,
        websocket: WebSocket,
        raw_headers: list[tuple[bytes, bytes]],
    ) -> list[dict[str, Any]]:
        """Update virtual cookie jar and build WS cookie commands from response.

        Returns list of cookie commands to send to the client.
        """
        from pywire.runtime.internal_request import (
            get_set_cookie_headers,
            parse_set_cookie_value,
        )

        commands: list[dict[str, Any]] = []
        virtual = self._connection_cookies.setdefault(websocket, {})
        httponly_set = self._connection_httponly.setdefault(websocket, set())

        for _name, value in get_set_cookie_headers(raw_headers):
            parsed = parse_set_cookie_value(value.decode("latin-1"))
            if not parsed:
                continue

            key = parsed["key"]
            max_age = parsed.get("max_age")

            # Check if this is a deletion (max-age=0 or negative)
            if max_age is not None and max_age <= 0:
                # Tombstone: None masks any baseline handshake cookie in
                # `_get_merged_cookies` so subsequent SPA navs don't resurrect it.
                virtual[key] = None  # type: ignore[assignment]
                httponly_set.discard(key)
                commands.append(
                    {
                        "cmd": "delete_cookie",
                        "refId": "__page__",
                        "args": {
                            "key": key,
                            "path": parsed.get("path", "/"),
                        },
                    }
                )
            else:
                virtual[key] = parsed["value"]
                if parsed.get("httponly"):
                    httponly_set.add(key)
                else:
                    httponly_set.discard(key)
                args: dict[str, Any] = {
                    "key": key,
                    "value": parsed["value"],
                }
                if "path" in parsed:
                    args["path"] = parsed["path"]
                if "max_age" in parsed:
                    args["max_age"] = parsed["max_age"]
                if parsed.get("secure"):
                    args["secure"] = True
                if parsed.get("samesite"):
                    args["samesite"] = parsed["samesite"]
                commands.append(
                    {
                        "cmd": "set_cookie",
                        "refId": "__page__",
                        "args": args,
                    }
                )

        return commands

    def _reconcile_from_client_cookies(
        self, websocket: WebSocket, cookie_header: str
    ) -> None:
        """Sync the virtual jar against ``document.cookie`` from the client.

        Non-httponly cookies visible to JavaScript are authoritative on the
        client — the user (or a third-party script) may have deleted or
        rewritten one between SPA navigations. httponly cookies tracked in
        ``_connection_httponly`` stay authoritative server-side because JS
        can neither read nor delete them.

        Anything the client reports is treated as truth for non-httponly
        keys; anything previously in the jar or handshake that the client
        no longer carries is tombstoned so middleware doesn't see a ghost
        cookie.
        """
        from pywire.runtime.internal_request import parse_cookie_header

        client_cookies = parse_cookie_header(cookie_header) if cookie_header else {}
        virtual = self._connection_cookies.setdefault(websocket, {})
        httponly_set = self._connection_httponly.setdefault(websocket, set())
        baseline = self._get_handshake_cookies(websocket)

        # 0. Infer HttpOnly for any baseline cookie the client can't see,
        #    but ONLY on the first reconcile for this connection. Rationale:
        #      - document.cookie omits HttpOnly by definition; first-time
        #        absence from the client payload implies HttpOnly.
        #      - On subsequent reconciles we trust the client: the user
        #        may have legitimately cleared a non-HttpOnly cookie via
        #        devtools or JS.
        #      - When the first reconcile's client payload is empty we
        #        can't distinguish HttpOnly from "user cleared all cookies".
        #        Default to HttpOnly: losing an auth session on the first
        #        SPA-nav after login is a much worse failure mode than
        #        carrying a deleted-via-JS non-HttpOnly cookie until the
        #        next hard reload (which clears the WS jar entirely).
        first_reconcile = websocket not in self._connection_reconciled
        if cookie_header is not None and first_reconcile:
            for key in baseline:
                if key not in client_cookies:
                    httponly_set.add(key)
        self._connection_reconciled.add(websocket)

        # 1. Adopt non-httponly client values (covers both rewrites and new
        #    cookies the client set locally).
        for key, value in client_cookies.items():
            if key in httponly_set:
                continue
            virtual[key] = value

        # 2. Tombstone non-httponly keys the client no longer carries.
        known_keys = set(baseline) | {k for k, v in virtual.items() if v is not None}
        for key in known_keys:
            if key in httponly_set:
                continue
            if key not in client_cookies:
                virtual[key] = None  # type: ignore[assignment]

    def _update_cookie_jar_from_commands(
        self, websocket: WebSocket, cookie_commands: list[dict[str, Any]]
    ) -> None:
        """Update virtual cookie jar when page sets cookies via WS commands."""
        virtual = self._connection_cookies.setdefault(websocket, {})
        for cmd in cookie_commands:
            if cmd.get("cmd") == "set_cookie":
                args = cmd.get("args", {})
                if "key" in args and "value" in args:
                    virtual[args["key"]] = args["value"]
            elif cmd.get("cmd") == "delete_cookie":
                args = cmd.get("args", {})
                if "key" in args:
                    # Tombstone — see `_get_merged_cookies`.
                    virtual[args["key"]] = None  # type: ignore[assignment]

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

                        # Migrate user state: copy all non-framework attributes.
                        # ``children`` holds a Snippet whose RenderUnit closes
                        # over the *old* page's render closures — copying it to
                        # the new page would bind stale, pre-reload code.
                        skip_attrs = {
                            "request",
                            "params",
                            "query",
                            "path",
                            "url",
                            "user",
                            "errors",
                            "loading",
                            "attrs",
                            "children",
                        }
                        from pywire.core.snippet import Snippet as _Snippet

                        for attr, value in old_page.__dict__.items():
                            if attr in skip_attrs or attr.startswith("_"):
                                continue
                            # Snippet values bind to the old page's render
                            # closures — leave the new page to re-create them.
                            if isinstance(value, _Snippet):
                                continue
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
