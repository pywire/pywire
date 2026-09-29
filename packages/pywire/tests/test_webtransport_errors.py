"""WebTransport error replies only carry the exception text in dev mode."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

from pywire.runtime.webtransport_handler import WebTransportHandler


def _failed_event_reply(dev_mode: bool) -> dict:
    app = MagicMock()
    app._is_dev_mode = dev_mode
    handler = WebTransportHandler(app)
    scope: dict = {}
    page = MagicMock()
    page.handle_event = AsyncMock(
        side_effect=RuntimeError("password authentication failed for user app")
    )
    handler.connection_pages[id(scope)] = page
    sent: list = []

    async def send(message: dict) -> None:
        sent.append(message)

    event = {"type": "event", "handler": "save", "data": {}, "id": 3}
    asyncio.run(handler._handle_message(event, scope, send, stream_id=0))
    return json.loads(sent[0]["data"])


def test_production_reply_hides_the_exception_text() -> None:
    assert _failed_event_reply(dev_mode=False) == {
        "type": "error",
        "error": "RuntimeError: An error occurred",
        "ack": 3,
    }


def test_dev_mode_reply_keeps_the_exception_text() -> None:
    reply = _failed_event_reply(dev_mode=True)
    assert reply["error"] == "password authentication failed for user app"
    assert reply["ack"] == 3
