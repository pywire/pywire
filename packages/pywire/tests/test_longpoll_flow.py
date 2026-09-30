"""The long-poll transport end to end, as the client drives it, and what a
failing event tells the browser on every transport."""

from __future__ import annotations

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire

PAGE = """---
count = wire(0)

def increment():
    count.value += 1

def boom():
    raise RuntimeError("could not connect to postgres://app:hunter2@db/prod")
---
<p id="c">{count}</p>
<button @click={increment}>+</button>
<button @click={boom}>x</button>
"""

MSGPACK = {"Content-Type": "application/x-msgpack"}


@pytest.fixture
def app(tmp_path):
    (tmp_path / "index.wire").write_text(PAGE)
    return PyWire(pages_dir=str(tmp_path))


def _open(client: TestClient) -> str:
    client.get("/")
    r = client.post(
        "/_pywire/session", content=msgpack.packb({"path": "/"}), headers=MSGPACK
    )
    assert r.status_code == 200
    return msgpack.unpackb(r.content, raw=False)["sessionId"]


def _event(client: TestClient, session: str, handler: str, event_id: int):
    return client.post(
        "/_pywire/event",
        content=msgpack.packb(
            {"handler": handler, "data": {}, "path": "/", "id": event_id}
        ),
        headers={**MSGPACK, "X-PyWire-Session": session},
    )


def test_events_on_a_long_poll_session_reach_the_page(app):
    with TestClient(app) as client:
        session = _open(client)
        for n in (1, 2):
            r = _event(client, session, "increment", n)
            assert r.status_code == 200
            reply = msgpack.unpackb(r.content, raw=False)
            assert reply.get("type") == "update", reply
            assert f">{n}</p>" in str(reply)


@pytest.mark.parametrize("debug", [False, True])
def test_a_failing_event_hides_its_exception_unless_debug(tmp_path, debug):
    (tmp_path / "index.wire").write_text(PAGE)
    app = PyWire(pages_dir=str(tmp_path), debug=debug)
    with TestClient(app, raise_server_exceptions=False) as client:
        session = _open(client)
        r = _event(client, session, "boom", 1)
        assert r.status_code == 500
        polled = msgpack.unpackb(r.content, raw=False)["error"]

        r = client.post(
            "/",
            json={"handler": "boom", "data": {}},
            headers={"X-PyWire-Event": "1"},
        )
        assert r.status_code == 500
        posted = r.json()["error"]

    for error in (polled, posted):
        if debug:
            assert "hunter2" in error
        else:
            assert error == "An error occurred"


def test_long_poll_sessions_are_capped(app):
    handler = app.http_handler
    handler.max_sessions_per_client = 3
    handler.max_sessions = 5
    with TestClient(app) as client:
        first = _open(client)
        opened = [_open(client) for _ in range(4)]
        assert len(handler.sessions) == 3
        assert first not in handler.sessions
        assert set(opened[-3:]) == set(handler.sessions)
        # The dropped session's client is told to open a new one.
        assert _event(client, first, "increment", 1).status_code == 404
