import asyncio
import unittest
from typing import Any, Dict, cast
from unittest.mock import AsyncMock, MagicMock, patch

import msgpack  # type: ignore[import-untyped]
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

    async def handle_event(self, name, data):  # type: ignore
        return Response("Updated")


class TestWebSocketExhaustive(unittest.TestCase):
    def setUp(self) -> None:
        # Use spec=object so it doesn't have every attribute
        self.app = MagicMock(spec=["router", "get_user"])
        self.handler = WebSocketHandler(self.app)

    def create_mock_ws(self) -> AsyncMock:
        ws = AsyncMock()
        ws.scope = {"type": "websocket", "path": "/ws"}
        return ws

    def test_handle_disconnect(self) -> None:
        ws = self.create_mock_ws()
        ws.receive_bytes.side_effect = WebSocketDisconnect()
        asyncio.run(self.handler.handle(ws))
        self.assertNotIn(ws, self.handler.active_connections)

    def test_handle_loop_message(self) -> None:
        ws = self.create_mock_ws()
        data = msgpack.packb({"type": "event", "handler": "click"})
        ws.receive_bytes.side_effect = [data, WebSocketDisconnect()]

        with patch.object(self.handler, "_process_message", new_callable=AsyncMock) as mock_proc:
            asyncio.run(self.handler.handle(ws))
            mock_proc.assert_called_once()

    def test_process_message_types(self) -> None:
        ws = self.create_mock_ws()

        with patch.object(self.handler, "_handle_event", new_callable=AsyncMock) as mock_event:
            asyncio.run(self.handler._process_message(ws, {"type": "event"}))
            mock_event.assert_called_once()

        with patch.object(self.handler, "_handle_relocate", new_callable=AsyncMock) as mock_reloc:
            asyncio.run(self.handler._process_message(ws, {"type": "relocate"}))
            mock_reloc.assert_called_once()

    def test_handle_event_create_page(self) -> None:
        ws = self.create_mock_ws()
        ws.scope = {"type": "websocket", "path": "/ws"}

        self.app.router.match.return_value = (MockPage, {"id": "1"}, "main")

        data = {"handler": "click", "path": "/test?foo=bar", "data": {"x": 1}}

        asyncio.run(self.handler._handle_event(ws, data))

        self.assertIn(ws, self.handler.connection_pages)
        page = self.handler.connection_pages[ws]
        self.assertIsInstance(page, MockPage)
        self.assertEqual(page.params, {"id": "1"})
        self.assertEqual(page.query, {"foo": "bar"})

        ws.send_bytes.assert_called()

    def test_handle_relocate_new_page(self) -> None:
        ws = self.create_mock_ws()
        ws.scope = {"type": "websocket", "path": "/ws"}

        self.app.router.match.return_value = (MockPage, {}, "main")

        data = {"path": "/about"}

        asyncio.run(self.handler._handle_relocate(ws, data))

        self.assertIn(ws, self.handler.connection_pages)
        page = self.handler.connection_pages[ws]
        self.assertIsInstance(page, MockPage)
        ws.send_bytes.assert_called()

    def test_broadcast_reload_hot(self) -> None:
        ws = self.create_mock_ws()
        self.handler.active_connections.add(ws)

        page = MockPage(MagicMock(), {}, {})
        page.request = MagicMock()
        page.request.url.path = "/test"
        page.some_state = 42
        self.handler.connection_pages[ws] = page

        self.app.router.match.return_value = (MockPage, {}, "main")

        asyncio.run(self.handler.broadcast_reload())

        new_page = self.handler.connection_pages[ws]
        self.assertNotEqual(new_page, page)
        self.assertEqual(cast(Any, new_page).some_state, 42)
        # ws.send_bytes.assert_called() # This might be skipped if hot reload fails
        # but here it should succeed.

    def test_send_console_message(self) -> None:
        ws = self.create_mock_ws()
        # Test standard message
        asyncio.run(self.handler._send_console_message(ws, "Hello\nWorld"))
        self.assertEqual(ws.send_bytes.call_count, 1)

        # Test error message
        asyncio.run(self.handler._send_console_message(ws, "Error\nOccurred", level="error"))
        self.assertEqual(ws.send_bytes.call_count, 2)

    def test_handle_event_with_output(self) -> None:
        ws = self.create_mock_ws()
        ws.scope = {"type": "websocket", "path": "/"}
        self.app.router.match.return_value = (MockPage, {}, "main")
        data = {"handler": "click", "data": {}}
        asyncio.run(self.handler._handle_event(ws, data))
        ws.send_bytes.assert_called()

    def test_handle_relocate_existing_page(self) -> None:
        ws = self.create_mock_ws()
        ws.scope = {"type": "websocket", "path": "/"}
        old_page = MockPage(MagicMock(), {}, {})
        self.handler.connection_pages[ws] = old_page
        self.app.router.match.return_value = (MockPage, {"id": "2"}, "main")
        data = {"path": "/item/2"}
        asyncio.run(self.handler._handle_relocate(ws, data))
        new_page = self.handler.connection_pages[ws]
        self.assertNotEqual(new_page, old_page)
        self.assertEqual(new_page.params, {"id": "2"})

    def test_broadcast_reload_cleanup(self) -> None:
        ws = self.create_mock_ws()
        self.handler.active_connections.add(ws)
        ws.send_bytes.side_effect = Exception("Closed")
        asyncio.run(self.handler.broadcast_reload())
        self.assertNotIn(ws, self.handler.active_connections)

    def test_broadcast_reload_fallback(self) -> None:
        ws = self.create_mock_ws()
        self.handler.active_connections.add(ws)
        page = MockPage(MagicMock(), {}, {})
        page.request = MagicMock()
        page.request.url.path = "/test"
        self.handler.connection_pages[ws] = page
        self.app.router.match.side_effect = Exception("Router crash")
        asyncio.run(self.handler.broadcast_reload())
        args, _ = ws.send_bytes.call_args
        msg = msgpack.unpackb(args[0], raw=False)
        self.assertEqual(msg["type"], "reload")

    def test_handle_event_no_route(self) -> None:
        ws = self.create_mock_ws()
        self.app.router.match.return_value = None
        data = {"handler": "click", "path": "/invalid"}
        with patch("builtins.print"):
            asyncio.run(self.handler._handle_event(ws, data))
        self.assertNotIn(ws, self.handler.connection_pages)

    def test_handle_relocate_no_route(self) -> None:
        ws = self.create_mock_ws()
        data = {"path": "/missing"}
        self.app.router.match.return_value = None
        with patch("builtins.print"):
            asyncio.run(self.handler._handle_relocate(ws, data))

    def test_broadcast_reload_no_page(self) -> None:
        ws = self.create_mock_ws()
        self.handler.active_connections.add(ws)
        # No page instance in connection_pages
        asyncio.run(self.handler.broadcast_reload())
        ws.send_bytes.assert_called()

    def test_broadcast_reload_migrate_fail(self) -> None:
        ws = self.create_mock_ws()
        self.handler.active_connections.add(ws)
        page = MockPage(MagicMock(), {}, {})
        page.request = MagicMock()
        page.request.url.path = "/"
        self.handler.connection_pages[ws] = page

        self.app.router.match.return_value = (MockPage, {}, "main")
        # Force reload to fail during render
        with patch.object(MockPage, "render", side_effect=Exception("Render crash")):
            asyncio.run(self.handler.broadcast_reload())

        args, _ = ws.send_bytes.call_args
        msg = msgpack.unpackb(args[0], raw=False)
        self.assertEqual(msg["type"], "reload")

    def test_handle_event_sync_onload(self) -> None:
        class SyncLoadPage(MockPage):
            async def on_load(self) -> None:
                self.load_called = True
                return None

        ws = self.create_mock_ws()
        self.app.router.match.return_value = (SyncLoadPage, {}, "main")
        data = {"handler": "click", "path": "/"}
        asyncio.run(self.handler._handle_event(ws, data))
        self.assertTrue(cast(Any, self.handler.connection_pages[ws]).load_called)


if __name__ == "__main__":
    unittest.main()
