import asyncio
import unittest
from unittest.mock import AsyncMock

from starlette.websockets import WebSocketDisconnect


class TestDebug(unittest.TestCase):
    def test_async_mock(self) -> None:
        ws = AsyncMock()
        ws.receive_bytes.side_effect = WebSocketDisconnect()

        async def run() -> None:
            await ws.receive_bytes()

        loop = asyncio.new_event_loop()
        with self.assertRaises(WebSocketDisconnect):
            loop.run_until_complete(run())


if __name__ == "__main__":
    unittest.main()
