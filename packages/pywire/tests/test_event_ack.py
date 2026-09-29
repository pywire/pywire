"""WebSocket replies to a client event echo its id as ``ack``.

The client binds each optimistic prediction to the id of the event it sent
and settles it when the reply carrying that id arrives, even when the reply's
morph never reaches the predicted control (its region didn't re-render).
"""

import shutil
import tempfile
from pathlib import Path
from typing import Any

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire

PAGE = """---
saved = wire(0)

def save():
    saved.value += 1

def boom():
    raise ValueError("nope")

def leave():
    navigate("/elsewhere")
---
<p id="status">{saved}</p>
<button @click={save}>save</button>
<button @click={boom}>boom</button>
<button @click={leave}>leave</button>
"""


@pytest.fixture()
def client():
    test_dir = tempfile.mkdtemp()
    pages = Path(test_dir) / "pages"
    pages.mkdir()
    (pages / "index.wire").write_text(PAGE)
    (pages / "elsewhere.wire").write_text("<p>elsewhere</p>")
    try:
        yield TestClient(PyWire(pages_dir=str(pages)), raise_server_exceptions=False)
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def _reply(ws: Any, message: dict) -> dict:
    ws.send_bytes(msgpack.packb(message))
    while True:
        data = msgpack.unpackb(ws.receive_bytes(), raw=False)
        if data["type"] != "console":
            return data


def _event(handler: str, event_id: Any) -> dict:
    return {
        "type": "event",
        "handler": handler,
        "path": "/",
        "data": {},
        "id": event_id,
    }


def test_event_replies_echo_the_event_id(client):
    with client.websocket_connect("/_pywire/ws") as ws:
        assert msgpack.unpackb(ws.receive_bytes(), raw=False)["type"] == "init"
        assert _reply(ws, {"type": "init", "path": "/"})["type"] == "init_ack"

        update = _reply(ws, _event("save", 1))
        assert (update["type"], update["ack"]) == ("update", 1)

        error = _reply(ws, _event("boom", 2))
        assert error["type"] in ("error", "error_trace")
        assert error["ack"] == 2

        nav = _reply(ws, _event("leave", 3))
        assert (nav["type"], nav["ack"]) == ("navigate", 3)


@pytest.mark.parametrize("event_id", [None, "7", True, 1.5])
def test_non_int_ids_are_not_echoed(client, event_id):
    with client.websocket_connect("/_pywire/ws") as ws:
        msgpack.unpackb(ws.receive_bytes(), raw=False)
        _reply(ws, {"type": "init", "path": "/"})
        update = _reply(ws, _event("save", event_id))
        assert update["type"] == "update"
        assert "ack" not in update
