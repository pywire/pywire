"""Tests for SecurityHeadersMiddleware and CSPBuilder."""

from __future__ import annotations

from typing import Any

import pytest

from pywire_secure.headers import CSPBuilder, SecurityHeadersMiddleware


class _OkApp:
    def __init__(self, *, headers: list[tuple[bytes, bytes]] | None = None) -> None:
        self._headers = headers or []

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": list(self._headers),
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})


class _Sink:
    def __init__(self) -> None:
        self.start: dict | None = None
        self.body: bytes = b""

    async def __call__(self, msg: dict) -> None:
        if msg["type"] == "http.response.start":
            self.start = msg
        elif msg["type"] == "http.response.body":
            self.body += msg.get("body", b"")


async def _noop_receive() -> dict:
    return {"type": "http.request", "body": b"", "more_body": False}


def _header_dict(start_msg: dict | None) -> dict[bytes, bytes]:
    assert start_msg is not None
    return {name: value for name, value in start_msg["headers"]}


@pytest.mark.asyncio
async def test_default_headers_present() -> None:
    mw = SecurityHeadersMiddleware(_OkApp())
    sink = _Sink()
    await mw({"type": "http"}, _noop_receive, sink)
    h = _header_dict(sink.start)
    assert h[b"x-content-type-options"] == b"nosniff"
    assert h[b"x-frame-options"] == b"SAMEORIGIN"
    assert h[b"referrer-policy"] == b"strict-origin-when-cross-origin"
    assert b"permissions-policy" in h


@pytest.mark.asyncio
async def test_hsts_off_by_default() -> None:
    mw = SecurityHeadersMiddleware(_OkApp())
    sink = _Sink()
    await mw({"type": "http"}, _noop_receive, sink)
    assert b"strict-transport-security" not in _header_dict(sink.start)


@pytest.mark.asyncio
async def test_csp_off_by_default() -> None:
    mw = SecurityHeadersMiddleware(_OkApp())
    sink = _Sink()
    await mw({"type": "http"}, _noop_receive, sink)
    assert b"content-security-policy" not in _header_dict(sink.start)


@pytest.mark.asyncio
async def test_hsts_when_set() -> None:
    mw = SecurityHeadersMiddleware(_OkApp(), hsts="max-age=31536000; includeSubDomains")
    sink = _Sink()
    await mw({"type": "http"}, _noop_receive, sink)
    assert (
        _header_dict(sink.start)[b"strict-transport-security"]
        == b"max-age=31536000; includeSubDomains"
    )


@pytest.mark.asyncio
async def test_csp_when_set() -> None:
    mw = SecurityHeadersMiddleware(_OkApp(), csp="default-src 'self'")
    sink = _Sink()
    await mw({"type": "http"}, _noop_receive, sink)
    assert _header_dict(sink.start)[b"content-security-policy"] == b"default-src 'self'"


@pytest.mark.asyncio
async def test_existing_header_preserved_not_overwritten() -> None:
    """If the downstream app set X-Frame-Options=DENY, we keep theirs.
    The middleware appends defaults only when missing."""
    inner = _OkApp(headers=[(b"x-frame-options", b"DENY")])
    mw = SecurityHeadersMiddleware(inner)
    sink = _Sink()
    await mw({"type": "http"}, _noop_receive, sink)
    assert _header_dict(sink.start)[b"x-frame-options"] == b"DENY"


@pytest.mark.asyncio
async def test_extra_headers_added() -> None:
    mw = SecurityHeadersMiddleware(_OkApp(), extra=[("X-Custom", "value")])
    sink = _Sink()
    await mw({"type": "http"}, _noop_receive, sink)
    assert _header_dict(sink.start)[b"x-custom"] == b"value"


@pytest.mark.asyncio
async def test_disable_default_with_none() -> None:
    mw = SecurityHeadersMiddleware(_OkApp(), x_frame_options=None)
    sink = _Sink()
    await mw({"type": "http"}, _noop_receive, sink)
    assert b"x-frame-options" not in _header_dict(sink.start)


@pytest.mark.asyncio
async def test_websocket_scope_skips_injection() -> None:
    """For non-HTTP scopes, the middleware passes send through verbatim
    so the downstream's headers reach the client untouched."""
    mw = SecurityHeadersMiddleware(_OkApp())
    sink = _Sink()

    async def receive() -> dict:
        return {"type": "websocket.connect"}

    await mw({"type": "websocket"}, receive, sink)
    h = _header_dict(sink.start)
    assert b"x-content-type-options" not in h
    assert b"x-frame-options" not in h


# --- CSPBuilder ---


def test_csp_default_src() -> None:
    csp = CSPBuilder().default_src("'self'").build()
    assert csp == "default-src 'self'"


def test_csp_multiple_directives() -> None:
    csp = (
        CSPBuilder()
        .default_src("'self'")
        .script_src("'self'", "https://cdn.example.com")
        .build()
    )
    assert "default-src 'self'" in csp
    assert "script-src 'self' https://cdn.example.com" in csp
    assert csp.count(";") == 1


def test_csp_repeated_directive_merges_sources() -> None:
    csp = (
        CSPBuilder().script_src("'self'").script_src("https://cdn.example.com").build()
    )
    assert csp == "script-src 'self' https://cdn.example.com"


def test_csp_duplicate_source_dedup() -> None:
    csp = CSPBuilder().script_src("'self'", "'self'").build()
    assert csp == "script-src 'self'"


def test_csp_upgrade_insecure_requests() -> None:
    csp = CSPBuilder().default_src("'self'").upgrade_insecure_requests().build()
    assert "upgrade-insecure-requests" in csp


def test_csp_block_all_mixed_content() -> None:
    csp = CSPBuilder().block_all_mixed_content().build()
    assert csp == "block-all-mixed-content"


def test_csp_arbitrary_directive_escape_hatch() -> None:
    csp = CSPBuilder().directive("manifest-src", "'self'").build()
    assert csp == "manifest-src 'self'"


def test_csp_report_uri() -> None:
    csp = CSPBuilder().report_uri("/csp-report").build()
    assert csp == "report-uri /csp-report"


def test_csp_empty_builder() -> None:
    assert CSPBuilder().build() == ""
