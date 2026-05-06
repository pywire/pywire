"""Tests for CSRFMiddleware ASGI behaviour.

Direct ASGI calls — no PyWire app dependency. The middleware is given
a tiny inner app that records what it sees, so the tests pin both the
gating logic (skip / accept / reject) and the body-replay contract
(downstream sees the same bytes the client sent).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import pytest

from pywire_secure.csrf import generate_token
from pywire_secure.middleware import CSRFMiddleware

SECRET = "test-secret-32-bytes-padded-xxxxxxxx"
SESSION = "session-abc-123"


class _RecordingApp:
    def __init__(self) -> None:
        self.scope: dict | None = None
        self.body: bytes = b""
        self.was_called: bool = False

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        self.scope = scope
        self.was_called = True
        more = True
        while more:
            msg = await receive()
            if msg["type"] != "http.request":
                break
            self.body += msg.get("body", b"")
            more = msg.get("more_body", False)
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send({"type": "http.response.body", "body": b"OK"})


class _Sink:
    def __init__(self) -> None:
        self.start: dict | None = None
        self.body: bytes = b""

    async def __call__(self, msg: dict) -> None:
        if msg["type"] == "http.response.start":
            self.start = msg
        elif msg["type"] == "http.response.body":
            self.body += msg.get("body", b"")


def _make_receive(body: bytes):
    sent = False

    async def receive() -> dict:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


def _scope(
    method: str,
    *,
    path: str = "/",
    headers: list[tuple[bytes, bytes]] | None = None,
    session_id: str | None = SESSION,
) -> dict:
    s: dict[str, Any] = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
    }
    if session_id is not None:
        s["pywire_session_id"] = session_id
    return s


@pytest.mark.asyncio
async def test_get_passes_through() -> None:
    inner = _RecordingApp()
    mw = CSRFMiddleware(inner, secret_key=SECRET)
    sink = _Sink()
    await mw(_scope("GET"), _make_receive(b""), sink)
    assert inner.was_called
    assert sink.start and sink.start["status"] == 200


@pytest.mark.asyncio
async def test_get_populates_csrf_token_in_scope() -> None:
    inner = _RecordingApp()
    mw = CSRFMiddleware(inner, secret_key=SECRET)
    sink = _Sink()
    await mw(_scope("GET"), _make_receive(b""), sink)
    assert inner.scope is not None
    token = inner.scope.get("pywire_csrf_token", "")
    assert token and ":" in token


@pytest.mark.asyncio
async def test_post_with_valid_header_token_passes() -> None:
    inner = _RecordingApp()
    mw = CSRFMiddleware(inner, secret_key=SECRET)
    sink = _Sink()
    token = generate_token(SESSION, SECRET)
    scope = _scope("POST", headers=[(b"x-csrf-token", token.encode())])
    await mw(scope, _make_receive(b""), sink)
    assert inner.was_called
    assert sink.start and sink.start["status"] == 200


@pytest.mark.asyncio
async def test_post_with_invalid_header_rejected_403() -> None:
    inner = _RecordingApp()
    mw = CSRFMiddleware(inner, secret_key=SECRET)
    sink = _Sink()
    scope = _scope("POST", headers=[(b"x-csrf-token", b"garbage")])
    await mw(scope, _make_receive(b""), sink)
    assert not inner.was_called
    assert sink.start and sink.start["status"] == 403


@pytest.mark.asyncio
async def test_post_without_token_rejected_403() -> None:
    inner = _RecordingApp()
    mw = CSRFMiddleware(inner, secret_key=SECRET)
    sink = _Sink()
    await mw(_scope("POST"), _make_receive(b""), sink)
    assert not inner.was_called
    assert sink.start and sink.start["status"] == 403


@pytest.mark.asyncio
async def test_post_with_form_field_token_passes_and_body_is_replayed() -> None:
    inner = _RecordingApp()
    mw = CSRFMiddleware(inner, secret_key=SECRET)
    sink = _Sink()
    token = generate_token(SESSION, SECRET)
    body = urlencode([("_csrf_token", token), ("name", "alice")]).encode()
    scope = _scope(
        "POST",
        headers=[(b"content-type", b"application/x-www-form-urlencoded")],
    )
    await mw(scope, _make_receive(body), sink)
    assert inner.was_called
    assert inner.body == body  # body replayed unchanged
    assert sink.start and sink.start["status"] == 200


@pytest.mark.asyncio
async def test_post_with_form_field_invalid_token_rejected() -> None:
    inner = _RecordingApp()
    mw = CSRFMiddleware(inner, secret_key=SECRET)
    sink = _Sink()
    body = urlencode([("_csrf_token", "wrong"), ("name", "alice")]).encode()
    scope = _scope(
        "POST",
        headers=[(b"content-type", b"application/x-www-form-urlencoded")],
    )
    await mw(scope, _make_receive(body), sink)
    assert not inner.was_called
    assert sink.start and sink.start["status"] == 403


@pytest.mark.asyncio
async def test_post_with_skip_path_passes_through() -> None:
    inner = _RecordingApp()
    mw = CSRFMiddleware(inner, secret_key=SECRET)
    sink = _Sink()
    await mw(_scope("POST", path="/_pywire/event"), _make_receive(b""), sink)
    assert inner.was_called


@pytest.mark.asyncio
async def test_post_without_session_passes_through() -> None:
    """No session = first-time visitor; no possible cross-origin forgery
    target yet. Failing closed would block every first POST."""
    inner = _RecordingApp()
    mw = CSRFMiddleware(inner, secret_key=SECRET)
    sink = _Sink()
    await mw(_scope("POST", session_id=None), _make_receive(b""), sink)
    assert inner.was_called


@pytest.mark.asyncio
async def test_websocket_scope_passes_through() -> None:
    inner = _RecordingApp()
    mw = CSRFMiddleware(inner, secret_key=SECRET)

    async def receive() -> dict:
        return {"type": "websocket.connect"}

    sink = _Sink()
    await mw({"type": "websocket"}, receive, sink)
    assert inner.was_called


@pytest.mark.asyncio
async def test_lifespan_scope_passes_through() -> None:
    inner = _RecordingApp()
    mw = CSRFMiddleware(inner, secret_key=SECRET)

    async def receive() -> dict:
        return {"type": "lifespan.startup"}

    sink = _Sink()
    await mw({"type": "lifespan"}, receive, sink)
    assert inner.was_called


@pytest.mark.asyncio
async def test_page_opt_out_via_csrf_required_attribute() -> None:
    class _OptOutPage:
        __csrf_required__ = False

    class _StubRouter:
        def match(self, path: str):
            return (_OptOutPage, {}, None)

    class _StubApp:
        router = _StubRouter()

    inner = _RecordingApp()
    mw = CSRFMiddleware(inner, secret_key=SECRET, pywire_app=_StubApp())
    sink = _Sink()
    await mw(_scope("POST"), _make_receive(b""), sink)
    assert inner.was_called  # opt-out page passes despite missing token


@pytest.mark.asyncio
async def test_oversize_body_rejected_without_buffering() -> None:
    """A 2 MiB form body must be rejected without exhausting memory.
    Token-via-header would still let the request through; this exercises
    the form-field path."""
    from pywire_secure.middleware import _MAX_BODY_BUFFER

    inner = _RecordingApp()
    mw = CSRFMiddleware(inner, secret_key=SECRET)
    sink = _Sink()
    body = b"a" * (_MAX_BODY_BUFFER + 1024)
    scope = _scope(
        "POST",
        headers=[(b"content-type", b"application/x-www-form-urlencoded")],
    )
    await mw(scope, _make_receive(body), sink)
    assert not inner.was_called
    assert sink.start and sink.start["status"] == 403


@pytest.mark.asyncio
async def test_disconnect_during_body_propagates_to_downstream() -> None:
    """If the client disconnects mid-body, the middleware must replay
    the disconnect so downstream's is_disconnected() doesn't lie."""
    inner_disconnect_seen = False

    class _DisconnectAwareApp:
        was_called = False
        body = b""

        async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
            nonlocal inner_disconnect_seen
            self.was_called = True
            for _ in range(5):
                msg = await receive()
                if msg["type"] == "http.disconnect":
                    inner_disconnect_seen = True
                    break
                if msg["type"] == "http.request":
                    self.body += msg.get("body", b"")
                    if not msg.get("more_body", False):
                        # Try one more receive to collect disconnect
                        continue
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/plain")],
                }
            )
            await send({"type": "http.response.body", "body": b"OK"})

    sent_count = 0

    async def disconnecting_receive() -> dict:
        nonlocal sent_count
        sent_count += 1
        if sent_count == 1:
            return {"type": "http.request", "body": b"first", "more_body": True}
        if sent_count == 2:
            return {"type": "http.disconnect"}
        return {"type": "http.disconnect"}

    inner = _DisconnectAwareApp()
    token = generate_token(SESSION, SECRET)
    mw = CSRFMiddleware(inner, secret_key=SECRET)
    sink = _Sink()
    scope = _scope(
        "POST",
        headers=[
            (b"content-type", b"application/x-www-form-urlencoded"),
            (b"x-csrf-token", token.encode()),
        ],
    )
    await mw(scope, disconnecting_receive, sink)
    # Header token bypassed body buffering — middleware accepts and
    # downstream handler runs and sees the disconnect propagated.
    assert inner.was_called
    assert inner_disconnect_seen


@pytest.mark.asyncio
async def test_post_with_multipart_field_token_passes() -> None:
    inner = _RecordingApp()
    mw = CSRFMiddleware(inner, secret_key=SECRET)
    sink = _Sink()
    token = generate_token(SESSION, SECRET)
    boundary = "----PyWireBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="_csrf_token"\r\n\r\n{token}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="name"\r\n\r\nalice\r\n'
        f"--{boundary}--\r\n"
    ).encode()
    scope = _scope(
        "POST",
        headers=[
            (b"content-type", f"multipart/form-data; boundary={boundary}".encode()),
        ],
    )
    await mw(scope, _make_receive(body), sink)
    assert inner.was_called
    assert sink.start and sink.start["status"] == 200
    assert inner.body == body
