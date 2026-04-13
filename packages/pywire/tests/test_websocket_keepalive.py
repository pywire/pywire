import asyncio
from typing import Any, Optional, cast
from unittest.mock import MagicMock

import msgpack
import pytest
from pywire.runtime.websocket import WebSocketHandler
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
        self.receive_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.closed = False
        self.close_code: Optional[int] = None
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_bytes(self) -> bytes:
        return await self.receive_queue.get()

    async def send_bytes(self, data: bytes) -> None:
        self.sent_messages.append(msgpack.unpackb(data, raw=False))

    async def close(self, code: int = 1000) -> None:
        self.closed = True
        self.close_code = code


class TestWebSocketKeepAlive:
    def setup_method(self, method: Any) -> None:
        self.app = MagicMock()
        self.app.router = MagicMock()
        self.app.ws_ping_interval = 25
        self.app.ws_ping_timeout = 10
        self.handler = WebSocketHandler(self.app)

    @pytest.mark.asyncio
    async def test_pong_message_sets_event(self) -> None:
        """Receiving a pong message should set the pong event."""
        ws = MockWebSocket()
        ws_key = cast(WebSocket, ws)
        event = asyncio.Event()
        self.handler._pong_events[ws_key] = event

        await self.handler._process_message(ws_key, {"type": "pong"})

        assert event.is_set()

    @pytest.mark.asyncio
    async def test_pong_without_event_is_harmless(self) -> None:
        """Receiving pong when no event is tracked should not raise."""
        ws = MockWebSocket()
        ws_key = cast(WebSocket, ws)

        # Should not raise
        await self.handler._process_message(ws_key, {"type": "pong"})

    @pytest.mark.asyncio
    async def test_ping_loop_sends_ping_and_waits_for_pong(self) -> None:
        """Ping loop should send a ping and succeed when pong arrives."""
        self.app.ws_ping_interval = 0  # No delay for test
        self.app.ws_ping_timeout = 5

        ws = MockWebSocket()
        ws_key = cast(WebSocket, ws)
        pong_event = asyncio.Event()
        self.handler._pong_events[ws_key] = pong_event

        async def respond_pong() -> None:
            # Wait for ping to be sent
            while not ws.sent_messages or ws.sent_messages[-1].get("type") != "ping":
                await asyncio.sleep(0.01)
            # Simulate client pong
            pong_event.set()

        pong_task = asyncio.create_task(respond_pong())
        ping_task = asyncio.create_task(self.handler._ping_loop(ws_key))

        # Let one ping/pong cycle complete, then cancel
        await asyncio.sleep(0.1)
        ping_task.cancel()
        pong_task.cancel()

        try:
            await ping_task
        except asyncio.CancelledError:
            pass

        # Verify a ping was sent
        ping_msgs = [m for m in ws.sent_messages if m.get("type") == "ping"]
        assert len(ping_msgs) >= 1

    @pytest.mark.asyncio
    async def test_ping_loop_closes_on_timeout(self) -> None:
        """Ping loop should close the WebSocket when pong times out."""
        self.app.ws_ping_interval = 0  # No delay for test
        self.app.ws_ping_timeout = 0.1  # Very short timeout

        ws = MockWebSocket()
        ws_key = cast(WebSocket, ws)
        pong_event = asyncio.Event()
        self.handler._pong_events[ws_key] = pong_event

        # Run ping loop — it will send ping, wait for pong, timeout, and close
        await self.handler._ping_loop(ws_key)

        # Verify ping was sent
        ping_msgs = [m for m in ws.sent_messages if m.get("type") == "ping"]
        assert len(ping_msgs) >= 1

        # Verify connection was closed
        assert ws.closed

    @pytest.mark.asyncio
    async def test_cleanup_cancels_ping_task(self) -> None:
        """_cleanup_connection should cancel the ping task."""
        ws = MockWebSocket()
        ws_key = cast(WebSocket, ws)

        self.handler.active_connections.add(ws_key)
        self.handler._pong_events[ws_key] = asyncio.Event()

        # Create a dummy long-running task
        async def dummy() -> None:
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(dummy())
        self.handler._ping_tasks[ws_key] = task

        self.handler._cleanup_connection(ws_key)

        # Let the event loop process the cancellation
        await asyncio.sleep(0)

        assert task.cancelled() or task.done()
        assert ws_key not in self.handler._ping_tasks
        assert ws_key not in self.handler._pong_events
        assert ws_key not in self.handler.active_connections

    @pytest.mark.asyncio
    async def test_ping_loop_exits_on_send_failure(self) -> None:
        """Ping loop should return if sending ping fails (connection closed)."""
        self.app.ws_ping_interval = 0
        self.app.ws_ping_timeout = 5

        ws = MockWebSocket()
        ws_key = cast(WebSocket, ws)
        pong_event = asyncio.Event()
        self.handler._pong_events[ws_key] = pong_event

        # Make send_bytes raise to simulate closed connection
        async def failing_send(data: bytes) -> None:
            raise RuntimeError("Connection closed")

        ws.send_bytes = failing_send  # type: ignore[assignment]

        # Should return without error
        await self.handler._ping_loop(ws_key)

        # Connection should not be marked as closed (that's the handler's job)
        assert not ws.closed
