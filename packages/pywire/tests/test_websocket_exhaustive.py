import pytest
import msgpack
from typing import Any, Dict, cast
from unittest.mock import AsyncMock, MagicMock, patch

from pywire.runtime.page import BasePage
from pywire.runtime.websocket import WebSocketHandler
from starlette.responses import Response
from starlette.websockets import WebSocketDisconnect


class MockPage(BasePage):
    def __init__(
        self, request: Any, params: Dict[str, str], query: Dict[str, str], **kwargs: Any
    ) -> None:
        super().__init__(request, params, query, **kwargs)
        self.load_called = False
        self.params = params
        self.query = query
        self.render_count: int = 0
        self.some_state: Any = None

    async def on_load(self) -> None:
        self.load_async_called = True

    async def render(self, init: bool = True) -> Response:
        self.render_count += 1
        return Response("<html></html>")

    async def handle_event(self, name, data):
        return Response("Updated")


class TestWebSocketExhaustive:
    def setup_method(self) -> None:
        # Use spec=object so it doesn't have every attribute
        self.app = MagicMock(spec=["router", "get_user"])
        self.handler = WebSocketHandler(self.app)

    def create_mock_ws(self) -> AsyncMock:
        ws = AsyncMock()
        ws.scope = {"type": "websocket", "path": "/ws"}
        return ws

    @pytest.mark.asyncio
    async def test_handle_disconnect(self) -> None:
        ws = self.create_mock_ws()
        ws.receive_bytes.side_effect = WebSocketDisconnect()
        await self.handler.handle(ws)
        assert ws not in self.handler.active_connections

    @pytest.mark.asyncio
    async def test_handle_loop_message(self) -> None:
        ws = self.create_mock_ws()
        data = msgpack.packb({"type": "event", "handler": "click"})
        ws.receive_bytes.side_effect = [data, WebSocketDisconnect()]

        with patch.object(self.handler, "_process_message", new_callable=AsyncMock) as mock_proc:
            await self.handler.handle(ws)
            mock_proc.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_message_types(self) -> None:
        ws = self.create_mock_ws()

        with patch.object(self.handler, "_handle_event", new_callable=AsyncMock) as mock_event:
            await self.handler._process_message(ws, {"type": "event"})
            mock_event.assert_called_once()

        with patch.object(self.handler, "_handle_relocate", new_callable=AsyncMock) as mock_reloc:
            await self.handler._process_message(ws, {"type": "relocate"})
            mock_reloc.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_event_create_page(self) -> None:
        ws = self.create_mock_ws()
        ws.scope = {"type": "websocket", "path": "/ws"}

        self.app.router.match.return_value = (MockPage, {"id": "1"}, "main")

        data = {"handler": "click", "path": "/test?foo=bar", "data": {"x": 1}}

        await self.handler._handle_event(ws, data)

        assert ws in self.handler.connection_pages
        page = self.handler.connection_pages[ws]
        assert isinstance(page, MockPage)
        assert page.params == {"id": "1"}
        assert page.query == {"foo": "bar"}

        ws.send_bytes.assert_called()

    @pytest.mark.asyncio
    async def test_handle_relocate_new_page(self) -> None:
        ws = self.create_mock_ws()
        ws.scope = {"type": "websocket", "path": "/ws"}

        self.app.router.match.return_value = (MockPage, {}, "main")

        data = {"path": "/about"}

        await self.handler._handle_relocate(ws, data)

        assert ws in self.handler.connection_pages
        page = self.handler.connection_pages[ws]
        assert isinstance(page, MockPage)
        ws.send_bytes.assert_called()

    @pytest.mark.asyncio
    async def test_broadcast_reload_hot(self) -> None:
        ws = self.create_mock_ws()
        self.handler.active_connections.add(ws)

        page = MockPage(MagicMock(), {}, {})
        page.request = MagicMock()
        page.request.url.path = "/test"
        page.some_state = 42
        self.handler.connection_pages[ws] = page

        self.app.router.match.return_value = (MockPage, {}, "main")

        await self.handler.broadcast_reload()

        new_page = self.handler.connection_pages[ws]
        assert new_page != page
        assert cast(Any, new_page).some_state == 42

    @pytest.mark.asyncio
    async def test_send_console_message(self) -> None:
        ws = self.create_mock_ws()
        # Test standard message
        await self.handler._send_console_message(ws, "Hello\nWorld")
        assert ws.send_bytes.call_count == 1

        # Test error message
        await self.handler._send_console_message(ws, "Error\nOccurred", level="error")
        assert ws.send_bytes.call_count == 2

    @pytest.mark.asyncio
    async def test_handle_event_with_output(self) -> None:
        ws = self.create_mock_ws()
        ws.scope = {"type": "websocket", "path": "/"}
        self.app.router.match.return_value = (MockPage, {}, "main")
        data = {"handler": "click", "data": {}}
        await self.handler._handle_event(ws, data)
        ws.send_bytes.assert_called()

    @pytest.mark.asyncio
    async def test_handle_relocate_existing_page(self) -> None:
        ws = self.create_mock_ws()
        ws.scope = {"type": "websocket", "path": "/"}
        old_page = MockPage(MagicMock(), {}, {})
        self.handler.connection_pages[ws] = old_page
        self.app.router.match.return_value = (MockPage, {"id": "2"}, "main")
        data = {"path": "/item/2"}
        await self.handler._handle_relocate(ws, data)
        new_page = self.handler.connection_pages[ws]
        assert new_page != old_page
        assert new_page.params == {"id": "2"}

    @pytest.mark.asyncio
    async def test_broadcast_reload_cleanup(self) -> None:
        ws = self.create_mock_ws()
        self.handler.active_connections.add(ws)
        ws.send_bytes.side_effect = Exception("Closed")
        await self.handler.broadcast_reload()
        assert ws not in self.handler.active_connections

    @pytest.mark.asyncio
    async def test_broadcast_reload_fallback(self) -> None:
        ws = self.create_mock_ws()
        self.handler.active_connections.add(ws)
        page = MockPage(MagicMock(), {}, {})
        page.request = MagicMock()
        page.request.url.path = "/test"
        self.handler.connection_pages[ws] = page
        self.app.router.match.side_effect = Exception("Router crash")
        await self.handler.broadcast_reload()
        args, _ = ws.send_bytes.call_args
        msg = msgpack.unpackb(args[0], raw=False)
        assert msg["type"] == "reload"

    @pytest.mark.asyncio
    async def test_handle_event_no_route(self) -> None:
        ws = self.create_mock_ws()
        self.app.router.match.return_value = None
        data = {"handler": "click", "path": "/invalid"}
        with patch("builtins.print"):
            await self.handler._handle_event(ws, data)
        assert ws not in self.handler.connection_pages

    @pytest.mark.asyncio
    async def test_handle_relocate_no_route(self) -> None:
        ws = self.create_mock_ws()
        data = {"path": "/missing"}
        self.app.router.match.return_value = None
        with patch("builtins.print"):
            await self.handler._handle_relocate(ws, data)

    @pytest.mark.asyncio
    async def test_broadcast_reload_no_page(self) -> None:
        ws = self.create_mock_ws()
        self.handler.active_connections.add(ws)
        # No page instance in connection_pages
        await self.handler.broadcast_reload()
        ws.send_bytes.assert_called()

    @pytest.mark.asyncio
    async def test_broadcast_reload_migrate_fail(self) -> None:
        ws = self.create_mock_ws()
        self.handler.active_connections.add(ws)
        page = MockPage(MagicMock(), {}, {})
        page.request = MagicMock()
        page.request.url.path = "/"
        self.handler.connection_pages[ws] = page

        self.app.router.match.return_value = (MockPage, {}, "main")
        # Force reload to fail during render
        with patch.object(MockPage, "render", side_effect=Exception("Render crash")):
            await self.handler.broadcast_reload()

        args, _ = ws.send_bytes.call_args
        msg = msgpack.unpackb(args[0], raw=False)
        assert msg["type"] == "reload"

    @pytest.mark.asyncio
    async def test_handle_event_sync_onload(self) -> None:
        class SyncLoadPage(MockPage):
            async def on_load(self) -> None:
                self.load_called = True
                return None

        ws = self.create_mock_ws()
        self.app.router.match.return_value = (SyncLoadPage, {}, "main")
        data = {"handler": "click", "path": "/"}
        await self.handler._handle_event(ws, data)
        assert cast(Any, self.handler.connection_pages[ws]).load_called is True
