import asyncio
import pytest
from typing import Any, Dict, Optional, cast
from unittest.mock import AsyncMock, MagicMock

import msgpack
from pywire.runtime.page import BasePage
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


class TestWebSocketHandler:
    def setup_method(self, method) -> None:
        self.app = MagicMock()
        self.app.router = MagicMock()
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
        ws = MockWebSocket()

        # Setup router mock
        # match returns (PageClass, params, match_type)
        self.app.router.match.return_value = (MockPage, {"id": "123"}, "main")

        data = {"type": "relocate", "path": "/new-path"}

        await self.handler._handle_relocate(cast(WebSocket, ws), data)

        assert cast(WebSocket, ws) in self.handler.connection_pages
        page = self.handler.connection_pages[cast(WebSocket, ws)]
        assert isinstance(page, MockPage)
        assert page.params == {"id": "123"}
        assert ws.sent_messages[0]["type"] == "update"

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
        await store.set("existing-session", {"attrs": {"count": 5}, "wire_tags": {}}, ttl=60)

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

        init_ack = next(
            (m for m in ws.sent_messages if m["type"] == "init_ack"), None
        )
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

        init_ack = next(
            (m for m in ws.sent_messages if m["type"] == "init_ack"), None
        )
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

        init_ack = next(
            (m for m in ws.sent_messages if m["type"] == "init_ack"), None
        )
        assert init_ack is not None
        assert init_ack["session_restored"] is False
