"""HTTP transport handler for PyWire fallback."""

import asyncio
import inspect
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import msgpack  # type: ignore
from starlette.requests import Request
from starlette.responses import Response

from pywire.runtime.page import BasePage


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
            expired = [sid for sid, session in self.sessions.items() if session.is_expired()]
            for sid in expired:
                del self.sessions[sid]
            if expired:
                print(f"PyWire: Cleaned up {len(expired)} expired HTTP sessions")

    async def create_session(self, request: Request) -> Response:
        """Create a new HTTP polling session."""
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

        session_id = str(uuid.uuid4())
        session = HTTPSession(session_id=session_id, path=path)

        # Try to instantiate the page for this session
        match = self.app.router.match(path)
        if match:
            page_class, params, variant_name = match
            query = dict(request.query_params)

            # Build path info dict
            path_info = {}
            if hasattr(page_class, "__routes__"):
                for name in page_class.__routes__.keys():
                    path_info[name] = name == variant_name
            elif hasattr(page_class, "__route__"):
                path_info["main"] = True

            # Build URL helper
            from pywire.runtime.router import URLHelper

            url_helper = None
            if hasattr(page_class, "__routes__"):
                url_helper = URLHelper(page_class.__routes__)

            session.page = page_class(request, params, query, path=path_info, url=url_helper)

            if hasattr(self.app, "get_user"):
                session.page.user = self.app.get_user(request)

            # Run load hook
            if hasattr(session.page, "on_load"):
                if inspect.iscoroutinefunction(session.page.on_load):
                    await session.page.on_load()
                else:
                    session.page.on_load()

        self.sessions[session_id] = session
        self.start_cleanup_task()

        return Response(
            msgpack.packb({"sessionId": session_id}), media_type="application/x-msgpack"
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

            if session.page is None:
                # Recreate page if needed
                match = self.app.router.match(session.path)
                if not match:
                    return Response(
                        msgpack.packb({"error": "Page not found"}),
                        status_code=404,
                        media_type="application/x-msgpack",
                    )

                page_class, params, variant_name = match
                query = dict(request.query_params)

                # Build path info dict
                path_info = {}
                if hasattr(page_class, "__routes__"):
                    for name in page_class.__routes__.keys():
                        path_info[name] = name == variant_name
                elif hasattr(page_class, "__route__"):
                    path_info["main"] = True

                # Build URL helper
                from pywire.runtime.router import URLHelper

                url_helper = None
                if hasattr(page_class, "__routes__"):
                    url_helper = URLHelper(page_class.__routes__)

                session.page = page_class(request, params, query, path=path_info, url=url_helper)

                # Run load hook
                if hasattr(session.page, "on_load"):
                    if inspect.iscoroutinefunction(session.page.on_load):
                        await session.page.on_load()
                    else:
                        session.page.on_load()

            # Dispatch event
            response = await session.page.handle_event(handler_name, event_data)

            # Get updated HTML
            html = bytes(response.body).decode("utf-8")

            return Response(
                msgpack.packb({"type": "update", "html": html}), media_type="application/x-msgpack"
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
