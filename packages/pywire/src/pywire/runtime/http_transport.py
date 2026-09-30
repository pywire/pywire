"""HTTP transport handler for PyWire fallback."""

import asyncio
import inspect
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import msgpack
from starlette.requests import Request
from starlette.responses import Response

from pywire.auth.guard import AuthDenied, enforce_auth
from pywire.runtime.origin import is_cross_site
from pywire.runtime.page import BasePage
from pywire.runtime.page_resolver import resolve_page
from pywire.runtime.protocol import dropped, event_ack, for_another_page
from pywire import __version__

logger = logging.getLogger(__name__)


@dataclass
class HTTPSession:
    """Represents an HTTP polling session."""

    session_id: str
    path: str
    page: Optional[BasePage] = None
    pending_updates: List[Dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_poll: datetime = field(default_factory=datetime.now)
    update_event: asyncio.Event = field(default_factory=asyncio.Event)

    def is_expired(self, timeout_seconds: int = 300) -> bool:
        """Check if session has expired."""
        return datetime.now() - self.last_poll > timedelta(seconds=timeout_seconds)


class HTTPTransportHandler:
    """Handles HTTP long-polling connections for PyWire fallback transport."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.sessions: Dict[str, HTTPSession] = {}
        self._cleanup_task: Optional[asyncio.Task] = None

    def start_cleanup_task(self) -> None:
        """Start background task to clean up expired sessions."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        """Periodically clean up expired sessions."""
        while True:
            await asyncio.sleep(60)  # Check every minute
            expired = [
                sid for sid, session in self.sessions.items() if session.is_expired()
            ]
            for sid in expired:
                del self.sessions[sid]
            if expired:
                logger.debug("Cleaned up %d expired HTTP sessions", len(expired))

    async def _open_page(self, request: Request, path: str) -> Optional[BasePage]:
        """Build the page at ``path`` for ``request``'s principal, if routed."""
        result = resolve_page(self.app.router, path, base_scope=dict(request.scope))
        if result is None:
            return None
        page = result[0]
        await self._set_user(page, request)
        return page

    async def _set_user(self, page: BasePage, request: Request) -> None:
        """Act as the principal of this request (each event carries cookies).

        Resolved per request so a logout or revoked session stops the next
        event.
        """
        if not hasattr(self.app, "get_user"):
            return
        user = self.app.get_user(request)
        if inspect.isawaitable(user):
            user = await user
        page._act_as(user)

    @staticmethod
    def _refuse_cross_site(request: Request) -> Optional[Response]:
        # A session acts with the visitor's cookies, like a WebSocket: a
        # page on another site must not open or drive one.
        if not is_cross_site(request.headers):
            return None
        return Response(
            msgpack.packb({"error": "cross-site request"}),
            status_code=403,
            media_type="application/x-msgpack",
        )

    async def create_session(self, request: Request) -> Response:
        """Create a new HTTP polling session."""
        refused = self._refuse_cross_site(request)
        if refused is not None:
            return refused
        try:
            body = await request.body()
            if not body:
                # Allow empty body for initial connect
                data = {}
            else:
                try:
                    data = msgpack.unpackb(body, raw=False)
                except Exception:
                    # Fallback to JSON for compatibility if needed, or error
                    import json

                    data = json.loads(body)

            path = data.get("path", "/")
        except Exception:
            path = "/"

        if not isinstance(path, str):
            path = "/"

        session_id = str(uuid.uuid4())
        session = HTTPSession(session_id=session_id, path=path)

        # A page its !auth guard refuses is not kept: the first event
        # rebuilds it and is refused again, with a navigate.
        page = await self._open_page(request, path)
        if page is not None:
            try:
                await enforce_auth(page)
                session.page = page
            except AuthDenied:
                pass

        self.sessions[session_id] = session
        self.start_cleanup_task()

        # Persist initial state to session store
        if session.page:
            self.app.session_persister.schedule(session_id, session.page)

        return Response(
            msgpack.packb({"sessionId": session_id, "version": __version__}),
            media_type="application/x-msgpack",
        )

    async def poll(self, request: Request) -> Response:
        """Long-poll for updates."""
        session_id = request.query_params.get("session")

        if not session_id or session_id not in self.sessions:
            return Response(
                msgpack.packb({"error": "Session not found"}),
                status_code=404,
                media_type="application/x-msgpack",
            )

        session = self.sessions[session_id]
        session.last_poll = datetime.now()

        # Check if updates already pending
        if session.pending_updates:
            updates = session.pending_updates.copy()
            session.pending_updates.clear()
            session.update_event.clear()
            return Response(msgpack.packb(updates), media_type="application/x-msgpack")

        # Wait for updates with timeout
        try:
            await asyncio.wait_for(session.update_event.wait(), timeout=30.0)

            # Event set, get updates
            updates = session.pending_updates.copy()
            session.pending_updates.clear()
            session.update_event.clear()
            return Response(msgpack.packb(updates), media_type="application/x-msgpack")

        except asyncio.TimeoutError:
            # Return empty array on timeout
            return Response(msgpack.packb([]), media_type="application/x-msgpack")

    async def handle_event(self, request: Request) -> Response:
        """Handle an event from an HTTP client."""
        refused = self._refuse_cross_site(request)
        if refused is not None:
            return refused
        session_id = request.headers.get("X-PyWire-Session")

        if not session_id or session_id not in self.sessions:
            return Response(
                msgpack.packb({"error": "Session not found"}),
                status_code=404,
                media_type="application/x-msgpack",
            )

        session = self.sessions[session_id]
        session.last_poll = datetime.now()

        try:
            body = await request.body()
            data = msgpack.unpackb(body, raw=False)
            handler_name = data.get("handler")
            event_data = data.get("data", {})

            page = session.page
            if page is None:
                page = await self._open_page(request, session.path)
                if page is None:
                    return Response(
                        msgpack.packb({"error": "Page not found"}),
                        status_code=404,
                        media_type="application/x-msgpack",
                    )
            else:
                await self._set_user(page, request)

            if for_another_page(page, data.get("path")):
                return Response(
                    msgpack.packb(dropped(event_ack(data))),
                    media_type="application/x-msgpack",
                )

            # Dispatch event (handle_event runs the page's !auth guard first)
            try:
                update = await page.handle_event(handler_name, event_data)
            except AuthDenied as denied:
                session.page = None
                return Response(
                    msgpack.packb({"type": "navigate", "path": denied.location}),
                    media_type="application/x-msgpack",
                )
            session.page = page

            if isinstance(update, Response):
                html = bytes(update.body).decode("utf-8")
                payload: Dict[str, Any] = {"type": "update", "html": html}
            elif isinstance(update, dict) and update.get("type") == "regions":
                payload = {"type": "update", "regions": update.get("regions", [])}
            elif isinstance(update, dict) and update.get("type") == "full":
                payload = {"type": "update", "html": update.get("html", "")}
            else:
                payload = {"type": "error", "error": "Invalid update payload"}

            # Persist updated state
            if session.page:
                self.app.session_persister.schedule(session_id, session.page)

            return Response(
                msgpack.packb(payload),
                media_type="application/x-msgpack",
            )

        except Exception as e:
            return Response(
                msgpack.packb({"type": "error", "error": str(e)}),
                status_code=500,
                media_type="application/x-msgpack",
            )

    def queue_update(self, session_id: str, update: Dict[str, Any]) -> None:
        """Queue an update to be sent to a specific session."""
        if session_id in self.sessions:
            self.sessions[session_id].pending_updates.append(update)
            self.sessions[session_id].update_event.set()

    def broadcast_reload(self) -> None:
        """Queue reload message to all sessions."""
        for session in self.sessions.values():
            session.pending_updates.append({"type": "reload"})
            session.update_event.set()
