"""Every live transport runs a page's !auth guard before any user code.

The WebSocket and HTTP long-poll transports used to attach a page to the
connection and dispatch events without the guard: an anonymous client could
send ``{"type": "event", "path": "/admin", "handler": ...}`` and the handler
ran before the guard's redirect. The guard now runs inside
``BasePage.handle_event`` (so every transport gets it, on every event), and
a refused page is never kept on the connection. Each test probes a side
effect (a file the handler or ``@mount`` hook writes) to prove no user code
ran.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import msgpack
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from pywire.auth import ClaimsPrincipal, MemoryAuthChannel
from pywire.auth.guard import AuthDenied
from pywire.runtime.app import PyWire

ALICE = ClaimsPrincipal(is_authenticated=True, name="Alice", user_id="u1")


class _App(PyWire):
    """Principal comes from a class flag, for HTTP requests and sockets alike."""

    signed_in = False

    def get_user(self, request_or_websocket: Any) -> Any:
        return ALICE if _App.signed_in else None


@pytest.fixture(autouse=True)
def _signed_out():
    _App.signed_in = False
    yield
    _App.signed_in = False


def _make_app(tmp_path: Path) -> tuple[_App, Path, Path]:
    probe = tmp_path / "handler_ran"
    mounted = tmp_path / "mount_ran"
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "admin.wire").write_text(
        "!auth\n"
        "---\n"
        "count = wire(0)\n"
        "def boom(e=None):\n"
        f"    open({str(probe)!r}, 'a').write('x')\n"
        "    count.value += 1\n"
        "@mount\n"
        "def on_mount():\n"
        f"    open({str(mounted)!r}, 'a').write('x')\n"
        "---\n"
        "<button @click={boom}>{count.value}</button>\n"
    )
    (pages / "index.wire").write_text("<p>home</p>\n")
    (pages / "login.wire").write_text("<p>login</p>\n")
    return _App(pages_dir=str(pages)), probe, mounted


def _recv(ws: Any) -> dict:
    return msgpack.unpackb(ws.receive_bytes(), raw=False)


def _send(ws: Any, message: dict) -> None:
    ws.send_bytes(msgpack.packb(message))


def _event(**extra: Any) -> dict:
    return {"type": "event", "path": "/admin", "handler": "boom", "data": {}, **extra}


# --- WebSocket ---------------------------------------------------------------


def test_ws_event_without_init_is_refused(tmp_path: Path) -> None:
    app, probe, mounted = _make_app(tmp_path)
    with TestClient(app).websocket_connect("/_pywire/ws") as ws:
        _recv(ws)  # init/version
        _send(ws, _event(id=7))
        assert _recv(ws) == {"type": "navigate", "path": "/login", "ack": 7}
        assert not app.ws_handler.connection_pages
    assert not probe.exists(), "handler ran for an anonymous client"
    assert not mounted.exists()


def test_ws_init_then_event_is_refused(tmp_path: Path) -> None:
    app, probe, mounted = _make_app(tmp_path)
    with TestClient(app).websocket_connect("/_pywire/ws") as ws:
        _recv(ws)
        _send(ws, {"type": "init", "path": "/admin"})
        assert _recv(ws) == {"type": "navigate", "path": "/login"}
        assert not app.ws_handler.connection_pages
        _send(ws, _event())
        assert _recv(ws) == {"type": "navigate", "path": "/login"}
    assert not probe.exists(), "handler ran for an anonymous client"
    assert not mounted.exists(), "@mount ran on a refused page"


def test_ws_render_request_is_refused(tmp_path: Path) -> None:
    """An event with no handler re-renders the page: guarded too."""
    app, _probe, _mounted = _make_app(tmp_path)
    with TestClient(app).websocket_connect("/_pywire/ws") as ws:
        _recv(ws)
        _send(ws, {"type": "event", "path": "/admin", "data": {}})
        assert _recv(ws) == {"type": "navigate", "path": "/login"}


def test_ws_signed_in_user_still_dispatches(tmp_path: Path) -> None:
    _App.signed_in = True
    app, probe, mounted = _make_app(tmp_path)
    with TestClient(app).websocket_connect("/_pywire/ws") as ws:
        _recv(ws)
        _send(ws, {"type": "init", "path": "/admin"})
        assert _recv(ws)["type"] == "init_ack"
        _send(ws, _event())
        assert _recv(ws)["type"] == "update"
    assert probe.read_text() == "x"
    assert mounted.read_text() == "x"


def test_ws_revoke_detaches_page_and_sticks(tmp_path: Path) -> None:
    """After a live revoke the page is dropped, and the socket's stale
    handshake principal cannot re-open it with a fresh event."""
    _App.signed_in = True
    app, probe, _mounted = _make_app(tmp_path)
    channel = MemoryAuthChannel()
    app._auth_channel = channel
    with TestClient(app) as client:
        with client.websocket_connect("/_pywire/ws") as ws:
            _recv(ws)
            _send(ws, {"type": "init", "path": "/admin"})
            assert _recv(ws)["type"] == "init_ack"
            _send(ws, _event())
            assert _recv(ws)["type"] == "update"
            assert probe.read_text() == "x"

            client.portal.call(channel.revoke, "u1")
            assert _recv(ws) == {"type": "navigate", "path": "/login"}
            assert not app.ws_handler.connection_pages

            _send(ws, _event())
            assert _recv(ws) == {"type": "navigate", "path": "/login"}
    assert probe.read_text() == "x", "handler ran after the session was revoked"


def test_ws_relocate_to_guarded_page_is_refused(tmp_path: Path) -> None:
    app, probe, mounted = _make_app(tmp_path)
    with TestClient(app).websocket_connect("/_pywire/ws") as ws:
        _recv(ws)
        _send(ws, {"type": "relocate", "path": "/admin"})
        assert _recv(ws) == {"type": "navigate", "path": "/login"}
        assert not app.ws_handler.connection_pages
    assert not probe.exists()
    assert not mounted.exists()


# --- WebSocket handshake origin ------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": "https://evil.example"},
        {"origin": "null"},
        {"origin": "http://testserver", "sec-fetch-site": "same-site"},
        {"origin": "https://evil.example", "sec-fetch-site": "cross-site"},
    ],
)
def test_ws_handshake_refuses_cross_site(tmp_path: Path, headers: dict) -> None:
    app, _probe, _mounted = _make_app(tmp_path)
    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect("/_pywire/ws", headers=headers) as ws:
            ws.receive_bytes()


@pytest.mark.parametrize(
    "headers",
    [
        {},  # not a browser: nothing to protect
        {"origin": "http://testserver"},
        {"origin": "https://app.example", "x-forwarded-host": "app.example"},
        {"origin": "https://evil.example", "sec-fetch-site": "same-origin"},
    ],
)
def test_ws_handshake_accepts_same_origin(tmp_path: Path, headers: dict) -> None:
    app, _probe, _mounted = _make_app(tmp_path)
    with TestClient(app).websocket_connect("/_pywire/ws", headers=headers) as ws:
        assert _recv(ws)["type"] == "init"


# --- HTTP long-poll ----------------------------------------------------------


def _session(client: TestClient, path: str = "/admin", **headers: str) -> Any:
    return client.post(
        "/_pywire/session",
        content=msgpack.packb({"path": path}),
        headers={"content-type": "application/x-msgpack", **headers},
    )


def _poll_event(client: TestClient, sid: str) -> dict:
    r = client.post(
        "/_pywire/event",
        content=msgpack.packb({"handler": "boom", "data": {}, "path": "/admin"}),
        headers={"X-PyWire-Session": sid, "content-type": "application/x-msgpack"},
    )
    assert r.status_code == 200
    return msgpack.unpackb(r.content, raw=False)


def test_long_poll_anonymous_event_is_refused(tmp_path: Path) -> None:
    app, probe, _mounted = _make_app(tmp_path)
    client = TestClient(app)
    sid = msgpack.unpackb(_session(client).content)["sessionId"]
    assert app.http_handler.sessions[sid].page is None
    assert _poll_event(client, sid) == {"type": "navigate", "path": "/login"}
    assert app.http_handler.sessions[sid].page is None
    assert not probe.exists(), "handler ran for an anonymous client"


def test_long_poll_logout_takes_effect_on_next_event(tmp_path: Path) -> None:
    _App.signed_in = True
    app, probe, _mounted = _make_app(tmp_path)
    client = TestClient(app)
    sid = msgpack.unpackb(_session(client).content)["sessionId"]
    assert _poll_event(client, sid)["type"] == "update"
    assert probe.read_text() == "x"

    _App.signed_in = False
    assert _poll_event(client, sid) == {"type": "navigate", "path": "/login"}
    assert probe.read_text() == "x", "handler ran after logout"


def test_long_poll_refuses_cross_site_session(tmp_path: Path) -> None:
    app, _probe, _mounted = _make_app(tmp_path)
    client = TestClient(app)
    r = _session(client, origin="https://evil.example")
    assert r.status_code == 403
    assert not app.http_handler.sessions


# --- The shared dispatch path ---------------------------------------------------


def test_handle_event_raises_before_dispatch(tmp_path: Path) -> None:
    """Any transport calling BasePage.handle_event gets the guard."""
    from pywire.runtime.page_resolver import resolve_page

    app, probe, _mounted = _make_app(tmp_path)
    result = resolve_page(app.router, "/admin", app=app)
    assert result is not None
    page = result[0]
    with pytest.raises(AuthDenied) as denied:
        asyncio.run(page.handle_event("boom", {}))
    assert denied.value.location == "/login"
    assert not probe.exists()
