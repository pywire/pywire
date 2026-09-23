"""Tests for ``RequestIDMiddleware``."""

from __future__ import annotations

from typing import Any

import pytest

from pywire_observability.middleware import (
    RequestIDMiddleware,
    _trace_id_from_traceparent,
)


class _RecordingApp:
    def __init__(self) -> None:
        self.scope: dict | None = None
        self.was_called: bool = False

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        self.scope = scope
        self.was_called = True
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

    async def __call__(self, msg: dict) -> None:
        if msg["type"] == "http.response.start":
            self.start = msg


async def _noop_receive() -> dict:
    return {"type": "http.request", "body": b"", "more_body": False}


def _scope(headers: list[tuple[bytes, bytes]] | None = None) -> dict:
    return {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers or [],
    }


@pytest.mark.asyncio
async def test_generates_id_when_no_inbound_header() -> None:
    inner = _RecordingApp()
    mw = RequestIDMiddleware(inner)
    sink = _Sink()
    await mw(_scope(), _noop_receive, sink)
    assert inner.scope is not None
    rid = inner.scope.get("pywire_request_id")
    assert rid and len(rid) == 32  # uuid4 hex
    # Echo header on response.
    assert sink.start is not None
    headers = dict(sink.start["headers"])
    assert headers.get(b"x-request-id") == rid.encode()


@pytest.mark.asyncio
async def test_uses_inbound_x_request_id() -> None:
    inner = _RecordingApp()
    mw = RequestIDMiddleware(inner)
    sink = _Sink()
    await mw(_scope([(b"x-request-id", b"my-known-id")]), _noop_receive, sink)
    assert inner.scope and inner.scope["pywire_request_id"] == "my-known-id"


@pytest.mark.asyncio
async def test_traceparent_takes_priority() -> None:
    inner = _RecordingApp()
    mw = RequestIDMiddleware(inner)
    sink = _Sink()
    trace_id = "0af7651916cd43dd8448eb211c80319c"
    traceparent = f"00-{trace_id}-b7ad6b7169203331-01"
    await mw(
        _scope([(b"traceparent", traceparent.encode()), (b"x-request-id", b"loser")]),
        _noop_receive,
        sink,
    )
    assert inner.scope and inner.scope["pywire_request_id"] == trace_id


@pytest.mark.asyncio
async def test_malformed_traceparent_falls_through() -> None:
    inner = _RecordingApp()
    mw = RequestIDMiddleware(inner)
    sink = _Sink()
    await mw(
        _scope(
            [
                (b"traceparent", b"garbage"),
                (b"x-request-id", b"fallback-value"),
            ]
        ),
        _noop_receive,
        sink,
    )
    assert inner.scope and inner.scope["pywire_request_id"] == "fallback-value"


@pytest.mark.asyncio
async def test_x_correlation_id_used_when_others_absent() -> None:
    inner = _RecordingApp()
    mw = RequestIDMiddleware(inner)
    sink = _Sink()
    await mw(_scope([(b"x-correlation-id", b"corr-1")]), _noop_receive, sink)
    assert inner.scope and inner.scope["pywire_request_id"] == "corr-1"


@pytest.mark.asyncio
async def test_websocket_scope_gets_id_no_response_echo() -> None:
    inner = _RecordingApp()
    mw = RequestIDMiddleware(inner)

    async def receive() -> dict:
        return {"type": "websocket.connect"}

    sink = _Sink()
    await mw({"type": "websocket", "headers": []}, receive, sink)
    assert inner.scope and inner.scope.get("pywire_request_id")


@pytest.mark.asyncio
async def test_lifespan_passes_through_unchanged() -> None:
    inner = _RecordingApp()
    mw = RequestIDMiddleware(inner)
    sink = _Sink()
    await mw({"type": "lifespan"}, _noop_receive, sink)
    assert inner.was_called
    assert inner.scope is not None
    assert "pywire_request_id" not in inner.scope


@pytest.mark.asyncio
async def test_request_id_ctx_set_during_handler() -> None:
    """ContextVar must be live while inner app runs — that's the whole
    point of the propagation."""
    from pywire.runtime.observability import request_id_ctx

    captured: dict[str, str | None] = {"id": None}

    class _Capturer:
        async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
            captured["id"] = request_id_ctx.get()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

    mw = RequestIDMiddleware(_Capturer())
    sink = _Sink()
    await mw(_scope([(b"x-request-id", b"live-check")]), _noop_receive, sink)
    assert captured["id"] == "live-check"
    # And reset after.
    assert request_id_ctx.get() is None


@pytest.mark.asyncio
async def test_existing_response_x_request_id_preserved() -> None:
    """If the inner app already set X-Request-ID, the middleware must
    not overwrite it (an upstream proxy may have echoed something)."""

    class _PrebakedApp:
        async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"x-request-id", b"already-set")],
                }
            )
            await send({"type": "http.response.body", "body": b""})

    mw = RequestIDMiddleware(_PrebakedApp())
    sink = _Sink()
    await mw(_scope(), _noop_receive, sink)
    headers = dict(sink.start["headers"])  # type: ignore[arg-type]
    assert headers[b"x-request-id"] == b"already-set"


# --- _trace_id_from_traceparent unit ---


@pytest.mark.parametrize(
    "header,expected",
    [
        (
            "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
            "0af7651916cd43dd8448eb211c80319c",
        ),
        (
            "00-0AF7651916CD43DD8448EB211C80319C-b7ad6b7169203331-01",
            None,  # uppercase trace_id is invalid per W3C
        ),
        ("garbage", None),
        ("", None),
        ("00-tooshort-b7ad6b7169203331-01", None),
        (
            # All-zeros trace_id is W3C-reserved as "invalid". Accepting
            # it would collapse every misconfigured-upstream request
            # into a single correlation bucket.
            "00-00000000000000000000000000000000-b7ad6b7169203331-01",
            None,
        ),
    ],
)
def test_trace_id_extraction(header: str, expected: str | None) -> None:
    assert _trace_id_from_traceparent(header) == expected


@pytest.mark.asyncio
async def test_all_zeros_traceparent_falls_through_to_uuid() -> None:
    """An invalid traceparent must NOT become the request_id —
    fall through to header priority, then UUID4."""
    inner = _RecordingApp()
    mw = RequestIDMiddleware(inner)
    sink = _Sink()
    await mw(
        _scope(
            [
                (
                    b"traceparent",
                    b"00-00000000000000000000000000000000-b7ad6b7169203331-01",
                )
            ]
        ),
        _noop_receive,
        sink,
    )
    assert inner.scope is not None
    rid = inner.scope["pywire_request_id"]
    assert rid != "0" * 32
    assert len(rid) == 32  # generated uuid4 hex
