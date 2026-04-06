import pytest
from unittest.mock import AsyncMock

from starlette.websockets import WebSocketDisconnect


class TestDebug:
    @pytest.mark.asyncio
    async def test_async_mock(self) -> None:
        ws = AsyncMock()
        ws.receive_bytes.side_effect = WebSocketDisconnect()

        with pytest.raises(WebSocketDisconnect):
            await ws.receive_bytes()
