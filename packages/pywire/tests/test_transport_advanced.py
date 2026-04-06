import pytest
from unittest.mock import AsyncMock, MagicMock

import msgpack
from pywire.runtime.app import PyWire
from pywire.runtime.http_transport import HTTPTransportHandler
from pywire.runtime.websocket import WebSocketHandler


@pytest.mark.asyncio
class TestTransportAdvanced:
    def setup_method(self, method) -> None:
        self.app = MagicMock(spec=PyWire)
        self.app.router = MagicMock()
        self.http_handler = HTTPTransportHandler(self.app)
        self.ws_handler = WebSocketHandler(self.app)

    async def test_http_session_cleanup(self) -> None:
        # Create session
        request = AsyncMock()
        request.json.return_value = {"path": "/"}
        request.query_params = {}

        page_class = MagicMock()
        self.app.router.match.return_value = (page_class, {}, "main")

        response = await self.http_handler.create_session(request)
        response = await self.http_handler.create_session(request)
        data = msgpack.unpackb(response.body, raw=False)
        session_id = data.get("sessionId")

        assert session_id in self.http_handler.sessions

        # Manually expire session or check cleanup logic (if public)
        # For now we just verify it exists
        assert self.http_handler.sessions[session_id] is not None

    async def test_websocket_error_handling(self) -> None:
        ws = AsyncMock()
        ws.receive_bytes.side_effect = Exception("Connection lost")

        # Should catch exception and not crash
        await self.ws_handler.handle(ws)
        # If it reached here without raising, it's good

    async def test_http_event_invalid_session(self) -> None:
        request = AsyncMock()
        request.headers = {"X-PyWire-Session": "invalid-id"}
        request.json.return_value = {"handler": "click", "data": {}}

        response = await self.http_handler.handle_event(request)
        assert response.status_code == 404
