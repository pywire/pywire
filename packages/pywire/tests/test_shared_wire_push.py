"""Writes to shared state reach every connected page, not just the writer.

A module-level ``wire()`` (or a ``producer()``) is shared by every session
in the process. When one session writes it, the other sessions' pages must
re-render without waiting for their own next event (#284).
"""

import sys
import threading
import uuid
from pathlib import Path
from typing import Any

import anyio
import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire


def _presence(module: str) -> str:
    return f"""---
from {module} import online

@mount
def join():
    online.value += 1

@unmount
def leave():
    online.value -= 1
---
<p id="online">online={{online}}</p>
"""


def _page(module: str) -> str:
    return f"""---
from {module} import votes, ticks
mine = wire(0)

def vote():
    votes.value += 1
    mine.value += 1
---
<p id="votes">votes={{votes}}</p>
<p id="ticks">ticks={{ticks}}</p>
<p id="mine">mine={{mine}}</p>
<button @click={{vote}}>vote</button>
"""


SHARED = """
from pywire import producer, wire

votes = wire(0)
online = wire(0)
_set = []


def _start(set_value):
    _set.append(set_value)


ticks = producer(0, _start)


def tick(n):
    _set[0](n)
"""


@pytest.fixture()
def app_and_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = f"shared_{uuid.uuid4().hex[:8]}"
    (tmp_path / f"{module}.py").write_text(SHARED)
    monkeypatch.syspath_prepend(str(tmp_path))
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.wire").write_text(_page(module))
    (pages / "presence.wire").write_text(_presence(module))
    yield PyWire(pages_dir=str(pages)), module
    sys.modules.pop(module, None)


def _recv(ws: Any, timeout: float = 3.0) -> dict:
    """Next non-console frame, failing instead of hanging if none arrives."""

    async def receive() -> Any:
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()

    while True:
        message = ws.portal.call(receive)
        data = msgpack.unpackb(message["bytes"], raw=False)
        if data["type"] != "console":
            return data


def _nothing_within(ws: Any, timeout: float = 0.3) -> bool:
    try:
        _recv(ws, timeout)
    except TimeoutError:
        return True
    return False


def _connect(ws: Any, path: str = "/") -> None:
    assert _recv(ws)["type"] == "init"
    ws.send_bytes(msgpack.packb({"type": "init", "path": path}))
    assert _recv(ws)["type"] == "init_ack"


def _click(ws: Any, handler: str) -> dict:
    ws.send_bytes(
        msgpack.packb(
            {"type": "event", "handler": handler, "path": "/", "data": {}, "id": 1}
        )
    )
    return _recv(ws)


def _html(update: dict) -> str:
    assert update["type"] == "update", update
    if "html" in update:
        return update["html"]
    return "".join(r.get("html", "") for r in update.get("regions", []))


def test_shared_wire_write_pushes_to_other_sessions(app_and_module):
    app, _ = app_and_module
    with TestClient(app) as client:  # one event loop, as in a real server
        with (
            client.websocket_connect("/_pywire/ws") as a,
            client.websocket_connect("/_pywire/ws") as b,
        ):
            _connect(a)
            _connect(b)

            reply = _html(_click(a, "vote"))
            assert "votes=1" in reply and "mine=1" in reply

            pushed = _html(_recv(b))
            assert "votes=1" in pushed
            # B's own state is untouched and nothing else is sent to A.
            assert "mine=1" not in pushed
            assert _nothing_within(a)


def test_writer_gets_one_reply_not_an_extra_push(app_and_module):
    app, _ = app_and_module
    with TestClient(app) as client:
        with client.websocket_connect("/_pywire/ws") as a:
            _connect(a)
            assert "votes=1" in _html(_click(a, "vote"))
            assert _nothing_within(a)


def test_producer_pushed_from_a_thread_reaches_idle_clients(app_and_module):
    app, module = app_and_module
    with TestClient(app) as client:
        with (
            client.websocket_connect("/_pywire/ws") as a,
            client.websocket_connect("/_pywire/ws") as b,
        ):
            _connect(a)
            _connect(b)

            worker = threading.Thread(target=sys.modules[module].tick, args=(7,))
            worker.start()
            worker.join()

            assert "ticks=7" in _html(_recv(a))
            assert "ticks=7" in _html(_recv(b))


def test_closed_connection_stops_receiving_pushes(app_and_module):
    app, module = app_and_module
    with TestClient(app) as client:
        with client.websocket_connect("/_pywire/ws") as a:
            _connect(a)
            with client.websocket_connect("/_pywire/ws") as b:
                _connect(b)
            # B is gone; A's write must not try to push to B's page.
            assert "votes=1" in _html(_click(a, "vote"))
            assert _nothing_within(a)


def test_unmount_runs_when_a_connection_closes(app_and_module):
    app, module = app_and_module
    with TestClient(app) as client:
        with client.websocket_connect("/_pywire/ws") as a:
            _connect(a, "/presence")
            # @mount runs after the first render; its write is pushed.
            assert "online=1" in _html(_recv(a))
            with client.websocket_connect("/_pywire/ws") as b:
                _connect(b, "/presence")
                assert "online=2" in _html(_recv(a))
            assert "online=1" in _html(_recv(a))
            assert sys.modules[module].online.value == 1
