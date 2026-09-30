import asyncio
import pytest
from typing import Any, Dict, Optional, cast
from unittest.mock import MagicMock

import msgpack
from pywire.runtime.page import BasePage
from pywire.runtime.session_persist import SessionPersister
from pywire.runtime.session_serializer import page_state_key, snapshot_page_state
from pywire.runtime.session_store import MemorySessionStore
from pywire.runtime.websocket import WebSocketHandler
from starlette.requests import Request
from starlette.responses import Response
from starlette.websockets import WebSocket


class MockWebSocket:
    def __init__(self, scope: dict | None = None) -> None:
        self.scope = scope or {
            "type": "websocket",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "client": ["127.0.0.1", 1234],
        }
        self.sent_messages: list[dict] = []
        self.receive_queue: asyncio.Queue = asyncio.Queue()
        self.closed = False
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_bytes(self) -> bytes:
        return cast(bytes, await self.receive_queue.get())

    async def send_bytes(self, data: bytes) -> None:
        self.sent_messages.append(msgpack.unpackb(data, raw=False))

    async def close(self, code: int = 1000) -> None:
        self.closed = True


class MockPage(BasePage):
    def __init__(
        self,
        request: Request,
        params: Dict[str, str],
        query: Dict[str, str],
        path: Optional[Dict[str, bool]] = None,
        url: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(request, params, query, path, url, **kwargs)
        self.event_called = False
        self.last_event_data: Optional[Dict[str, Any]] = None

    async def handle_event(
        self, event_name: str, event_data: Dict[str, Any]
    ) -> Response:
        self.event_called = True
        self.last_event_data = event_data
        # Return a real Response object
        from starlette.responses import Response

        return Response("<div>Test Page</div>")

    async def _render_template(self) -> str:
        return "<div>Test Page</div>"


def _page_at(path: str) -> MockPage:
    """A MockPage for ``path``, as ``resolve_page`` builds one on init."""
    scope = {
        "type": "http",
        "path": path,
        "headers": [],
        "query_string": b"",
        "method": "GET",
    }
    return MockPage(Request(scope), {}, {})


class TestWebSocketHandler:
    def setup_method(self, method) -> None:
        self.app = MagicMock()
        self.app.get_user.return_value = None
        self.app.router = MagicMock()
        self.app.session_persist_interval = 60
        self.app.session_persister = SessionPersister(self.app)
        self.handler = WebSocketHandler(self.app)

    @pytest.mark.asyncio
    async def test_process_message_event(self) -> None:
        ws = MockWebSocket()
        # Mock request object with correct HTTP type
        scope = dict(ws.scope)
        scope["type"] = "http"
        request = Request(scope=scope)
        page = MockPage(request, {}, {})
        self.handler.connection_pages[cast(WebSocket, ws)] = page

        data: Dict[str, Any] = {
            "type": "event",
            "handler": "test_handler",
            "data": {"key": "value"},
        }

        await self.handler._process_message(cast(WebSocket, ws), data)

        assert page.event_called
        assert page.last_event_data == {"key": "value"}

        # We might have captured console output from the print(f"DEBUG EVENT...")
        # so we check if the last message is update
        update_msg = next((m for m in ws.sent_messages if m["type"] == "update"), None)
        assert update_msg is not None
        assert cast(Dict[str, Any], update_msg)["type"] == "update"

    @pytest.mark.asyncio
    async def test_handle_relocate(self) -> None:
        """Relocate dispatches through internal ASGI replay and creates local page."""
        ws = MockWebSocket(
            scope={
                "type": "websocket",
                "path": "/",
                "headers": [(b"host", b"testserver")],
                "query_string": b"",
                "client": ("127.0.0.1", 1234),
                "server": ("testserver", 80),
                "scheme": "http",
                "root_path": "",
            }
        )

        # Setup router mock — used by resolve_page for local state instance
        self.app.router.match.return_value = (MockPage, {"id": "123"}, "main")

        # Mock _get_dispatch_target to return a minimal ASGI app that returns 200
        async def fake_asgi_app(scope: dict, receive: Any, send: Any) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/html")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b"<div>Relocated Page</div>",
                }
            )

        self.app._get_dispatch_target.return_value = fake_asgi_app

        data = {"type": "relocate", "path": "/new-path"}

        await self.handler._handle_relocate(cast(WebSocket, ws), data)

        # Should have a local page instance for WS state management
        assert cast(WebSocket, ws) in self.handler.connection_pages
        page = self.handler.connection_pages[cast(WebSocket, ws)]
        assert isinstance(page, MockPage)
        assert page.params == {"id": "123"}

        # First message should be the update with rendered HTML from internal dispatch
        update_msg = next(
            (m for m in ws.sent_messages if m.get("type") == "update"), None
        )
        assert update_msg is not None
        assert "Relocated Page" in update_msg.get("html", "")

    @pytest.mark.asyncio
    async def test_send_console_message(self) -> None:
        ws = MockWebSocket()
        await self.handler._send_console_message(cast(WebSocket, ws), "Hello Stdout")
        await self.handler._send_console_message(
            cast(WebSocket, ws), "Hello Stderr", level="error"
        )

        assert len(ws.sent_messages) == 2
        assert ws.sent_messages[0]["type"] == "console"
        assert ws.sent_messages[0]["level"] == "info"
        assert ws.sent_messages[0]["lines"] == ["Hello Stdout"]

        assert ws.sent_messages[1]["level"] == "error"
        assert ws.sent_messages[1]["lines"] == ["Hello Stderr"]

    @pytest.mark.asyncio
    async def test_init_ack_session_restored_true(self) -> None:
        """init_ack should include session_restored=True when session was found in store."""
        ws = MockWebSocket()
        store = MemorySessionStore()
        # Pre-populate a session
        saved = _page_at("/")
        saved.count = 5
        await store.set(
            page_state_key("existing-session", saved),
            snapshot_page_state(saved),
            ttl=60,
        )

        self.app.session_store = store
        self.app.router.match.return_value = (MockPage, {}, "main")
        self.app.debug = False
        self.app._is_dev_mode = False
        self.app.session_ttl = 60
        self.app.session_warn_size = 256 * 1024

        data = {
            "type": "init",
            "path": "/",
            "session_id": "existing-session",
        }
        await self.handler._handle_init(cast(WebSocket, ws), data)

        init_ack = next((m for m in ws.sent_messages if m["type"] == "init_ack"), None)
        assert init_ack is not None
        assert init_ack["session_restored"] is True
        assert init_ack["session_id"] == "existing-session"

    @pytest.mark.asyncio
    async def test_init_ack_session_restored_false_expired(self) -> None:
        """init_ack should include session_restored=False when session expired."""
        ws = MockWebSocket()
        store = MemorySessionStore()
        # No session in store — simulates expired session

        self.app.session_store = store
        self.app.router.match.return_value = (MockPage, {}, "main")
        self.app.debug = False
        self.app._is_dev_mode = False
        self.app.session_ttl = 60
        self.app.session_warn_size = 256 * 1024

        data = {
            "type": "init",
            "path": "/",
            "session_id": "expired-session",
        }
        await self.handler._handle_init(cast(WebSocket, ws), data)

        init_ack = next((m for m in ws.sent_messages if m["type"] == "init_ack"), None)
        assert init_ack is not None
        assert init_ack["session_restored"] is False
        # A new session_id should have been generated
        assert init_ack["session_id"] != "expired-session"

    @pytest.mark.asyncio
    async def test_init_ack_session_restored_false_fresh(self) -> None:
        """init_ack should include session_restored=False for a fresh connection (no session_id)."""
        ws = MockWebSocket()
        store = MemorySessionStore()

        self.app.session_store = store
        self.app.router.match.return_value = (MockPage, {}, "main")
        self.app.debug = False
        self.app._is_dev_mode = False
        self.app.session_ttl = 60
        self.app.session_warn_size = 256 * 1024

        data = {
            "type": "init",
            "path": "/",
        }
        await self.handler._handle_init(cast(WebSocket, ws), data)

        init_ack = next((m for m in ws.sent_messages if m["type"] == "init_ack"), None)
        assert init_ack is not None
        assert init_ack["session_restored"] is False

    @pytest.mark.asyncio
    async def test_reconnect_restores_state_held_by_persist_throttle(self) -> None:
        """A reconnect inside the persist window restores the latest state."""
        store = MemorySessionStore()
        self.app.session_store = store
        self.app.router.match.return_value = (MockPage, {}, "main")
        self.app.debug = False
        self.app._is_dev_mode = False
        self.app.session_ttl = 60
        self.app.session_warn_size = 256 * 1024
        persister = self.app.session_persister

        old_page = _page_at("/")
        old_page.count = 1
        persister.schedule("sess", old_page)
        for _ in range(3):
            await asyncio.sleep(0)
        old_page.count = 2
        persister.schedule("sess", old_page)  # held until the window closes
        stored = await store.get(page_state_key("sess", old_page))
        assert stored is not None and stored["attrs"]["count"] == 1

        ws = MockWebSocket()
        data = {"type": "init", "path": "/", "session_id": "sess"}
        await self.handler._handle_init(cast(WebSocket, ws), data)

        assert getattr(self.handler.connection_pages[ws], "count") == 2
        persister.flush("sess")
        await asyncio.sleep(0)


class _OtherMockPage(MockPage):
    pass


class TestReconnectRestoresOnlyItsOwnPage:
    """A client-sent session id restores state only into the page (class and
    path) it was saved from, for the same user, and never restores the user."""

    def setup_method(self, method) -> None:
        self.app = MagicMock()
        self.app.get_user.return_value = None
        self.app.router = MagicMock()
        self.app.session_persist_interval = 60
        self.app.session_persister = SessionPersister(self.app)
        self.app.session_store = MemorySessionStore()
        self.app.debug = False
        self.app._is_dev_mode = False
        self.app.session_ttl = 60
        self.app.session_warn_size = 256 * 1024
        self.handler = WebSocketHandler(self.app)

    async def _save(self, page: MockPage) -> None:
        self.app.session_persister.schedule("sess", page)
        await self.app.session_persister.settle("sess")

    async def _reconnect(self, page_class: type, path: str) -> tuple[Any, Any]:
        self.app.router.match.return_value = (page_class, {}, "main")
        ws = MockWebSocket()
        await self.handler._handle_init(
            cast(WebSocket, ws), {"type": "init", "path": path, "session_id": "sess"}
        )
        ack = next(m for m in ws.sent_messages if m["type"] == "init_ack")
        return self.handler.connection_pages[ws], ack

    @pytest.mark.asyncio
    async def test_same_page_restores(self) -> None:
        saved = _page_at("/a")
        saved.note = "secret-A"
        await self._save(saved)
        page, ack = await self._reconnect(MockPage, "/a")
        assert ack["session_restored"] is True
        assert getattr(page, "note") == "secret-A"

    @pytest.mark.asyncio
    async def test_other_path_does_not_restore(self) -> None:
        saved = _page_at("/a")
        saved.note = "secret-A"
        await self._save(saved)
        page, ack = await self._reconnect(MockPage, "/b")
        assert ack["session_restored"] is False
        assert not hasattr(page, "note")

    @pytest.mark.asyncio
    async def test_other_page_class_does_not_restore(self) -> None:
        saved = _page_at("/a")
        saved.note = "secret-A"
        await self._save(saved)
        page, ack = await self._reconnect(_OtherMockPage, "/a")
        assert ack["session_restored"] is False
        assert not hasattr(page, "note")

    @pytest.mark.asyncio
    async def test_user_is_never_restored(self) -> None:
        saved = _page_at("/a")
        saved.note = "alice's"
        saved.user = {"id": "alice"}
        await self._save(saved)
        # Alice logged out: the reconnecting request resolves nobody.
        page, ack = await self._reconnect(MockPage, "/a")
        assert ack["session_restored"] is False
        assert page.user is None
        assert not hasattr(page, "note")
        # Alice again: her state, with the user from the request.
        self.app.get_user.return_value = {"id": "alice"}
        page, ack = await self._reconnect(MockPage, "/a")
        assert ack["session_restored"] is True
        assert getattr(page, "note") == "alice's"
