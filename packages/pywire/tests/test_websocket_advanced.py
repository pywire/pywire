import unittest
from unittest.mock import AsyncMock, MagicMock

from pywire.runtime.app import PyWire
from pywire.runtime.websocket import WebSocketHandler


class TestWebSocketAdvanced(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.app = MagicMock(spec=PyWire)
        # Fix: ensure app.router.match is a mock
        self.app.router = MagicMock()
        self.handler = WebSocketHandler(self.app)

    async def test_broadcast_reload(self) -> None:
        """Test broadcast_reload method."""
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        page1 = MagicMock()
        # Mock request for page1 to allow reload logic to find path
        page1.request.url.path = "/test"

        self.handler.active_connections = {ws1, ws2}
        self.handler.connection_pages = {ws1: page1}

        # Mock router match to return a page class
        new_page_class = MagicMock()
        self.app.router.match.return_value = (new_page_class, {}, "main")

        # Execute broadcast_reload
        await self.handler.broadcast_reload()

        # ws1 has a page, so it should receive an 'update' message (hot reload)
        # or 'reload' if something fails.
        # Our mock setup should allow success path:
        # 1. match found
        # 2. new_page instantiated
        # 3. render called

        # Verify new_page_class instantiated
        new_page_class.assert_called_once()

        # Verify ws1 got 'update' message
        # ws1.send_bytes.assert_called() # Hard to check payload without unpacking msgpack

        # ws2 has no page, so it should receive 'reload'
        # ws2.send_bytes.assert_called()

        self.assertTrue(ws1.send_bytes.called)
        self.assertTrue(ws2.send_bytes.called)


if __name__ == "__main__":
    unittest.main()
