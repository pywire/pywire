"""Dev-only SSE reload channel for non-interactive server mode.

Non-interactive mode has no persistent WebSocket, so the WS-based hot
reload path does not apply. The dev server instead mounts a dev-only
Server-Sent Events endpoint that pushes ``reload`` / ``shutdown`` events
to connected browsers.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from starlette.requests import Request
from starlette.responses import StreamingResponse

_QUEUE_MAX = 8
_PING_INTERVAL = 15.0


class DevReloadBroadcaster:
    """Fan out reload/shutdown events to SSE subscribers."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=_QUEUE_MAX)
        async with self._lock:
            self._subscribers.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        async with self._lock:
            self._subscribers.discard(q)

    async def _broadcast(self, event: str, data: dict[str, Any]) -> None:
        msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        async with self._lock:
            targets = list(self._subscribers)
        for q in targets:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                # Slow client — drop. Next broadcast will catch up.
                pass

    async def broadcast_reload(self) -> None:
        await self._broadcast("reload", {"type": "reload"})

    async def broadcast_shutdown(self) -> None:
        await self._broadcast("shutdown", {"type": "shutdown"})

    def subscriber_count(self) -> int:
        return len(self._subscribers)


async def dev_reload_endpoint(request: Request) -> StreamingResponse:
    broadcaster: DevReloadBroadcaster | None = getattr(
        request.app.state, "dev_reload_broadcaster", None
    )
    if broadcaster is None:
        return StreamingResponse(iter([b""]), status_code=404, media_type="text/plain")

    async def stream() -> AsyncIterator[bytes]:
        q = await broadcaster.subscribe()
        try:
            yield b": connected\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=_PING_INTERVAL)
                    yield msg.encode()
                except asyncio.TimeoutError:
                    yield b": ping\n\n"
        finally:
            await broadcaster.unsubscribe(q)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
