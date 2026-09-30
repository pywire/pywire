"""WebTransport error replies only carry the exception text with debug=True."""

import asyncio
import functools
import json
from unittest.mock import AsyncMock, MagicMock

from pywire.runtime.app import PyWire
from pywire.runtime.webtransport_handler import WebTransportHandler


def _failed_event_reply(debug: bool) -> dict:
    app = MagicMock()
    app.debug = debug
    app._client_error = functools.partial(PyWire._client_error, app)
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
    assert _failed_event_reply(debug=False) == {
        "type": "error",
        "error": "An error occurred",
        "ack": 3,
    }


def test_init_builds_the_page_from_its_own_url(tmp_path) -> None:
    """A webtransport scope isn't an HTTP one: the page gets a request for
    the URL it was opened at, with the connection's headers."""
    (tmp_path / "items.wire").write_text("<p>{query.get('q', '')}</p>\n")
    app = PyWire(pages_dir=str(tmp_path))
    handler = WebTransportHandler(app)
    scope = {
        "type": "webtransport",
        "path": "/_pywire/webtransport",
        "query_string": b"",
        "headers": [(b"host", b"localhost")],
        "client": ("127.0.0.1", 1),
        "server": ("localhost", 443),
        "scheme": "https",
    }
    sent: list = []

    async def send(message: dict) -> None:
        sent.append(message)

    init = {"type": "init", "path": "/items?q=x"}
    asyncio.run(handler._handle_message(init, scope, send, stream_id=0))
    page = handler.connection_pages[id(scope)]
    assert page.request.url.path == "/items"
    assert page.query == {"q": "x"}


def test_debug_reply_keeps_the_exception_text() -> None:
    reply = _failed_event_reply(debug=True)
    assert reply["error"] == "RuntimeError: password authentication failed for user app"
    assert reply["ack"] == 3
