"""Gzip for pages, the client runtime and other text responses."""

import gzip

import pytest
from starlette.applications import Starlette
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire
from pywire.runtime.compression import CompressionMiddleware, is_compressible

PAGE = (
    """---
count = wire(0)
---
<p>{count}</p>
"""
    + "<p>padding so the page clears the minimum size</p>\n" * 20
)

GZIP = {"Accept-Encoding": "gzip"}
IDENTITY = {"Accept-Encoding": "identity"}


def make_app(tmp_path, **kwargs) -> PyWire:
    pages = tmp_path / "pages"
    pages.mkdir(exist_ok=True)
    (pages / "index.wire").write_text(PAGE)
    return PyWire(pages_dir=str(pages), **kwargs)


def test_page_is_gzipped_and_carries_no_overlay_markup(tmp_path) -> None:
    with TestClient(make_app(tmp_path)) as client:
        response = client.get("/", headers=GZIP)

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert "Accept-Encoding" in response.headers["vary"]
    assert response.num_bytes_downloaded < len(response.content)
    assert ">0</p>" in response.text
    assert "_pywire_reconnect" not in response.text


def test_page_is_plain_without_accept_encoding_or_when_disabled(tmp_path) -> None:
    with TestClient(make_app(tmp_path)) as client:
        assert "content-encoding" not in client.get("/", headers=IDENTITY).headers
    with TestClient(make_app(tmp_path, compress=False)) as client:
        assert "content-encoding" not in client.get("/", headers=GZIP).headers


def test_custom_reconnect_template_is_still_injected(tmp_path) -> None:
    app = make_app(tmp_path)
    (tmp_path / "pages" / "__reconnect__.wire").write_text(
        "<p class='mine'>Hold on</p>\n<style>.mine { color: red; }</style>\n"
    )
    app._load_reconnect_template(tmp_path / "pages" / "__reconnect__.wire")
    with TestClient(app) as client:
        html = client.get("/", headers=GZIP).text

    assert '<template id="_pywire_reconnect">' in html
    assert "Hold on" in html


def test_client_runtime_is_served_precompressed(tmp_path) -> None:
    app = make_app(tmp_path)
    with TestClient(app) as client:
        raw = client.get("/_pywire/static/pywire.core.min.js", headers=IDENTITY)
        gz = client.get("/_pywire/static/pywire.core.min.js", headers=GZIP)

    assert "content-encoding" not in raw.headers
    assert gz.headers["content-encoding"] == "gzip"
    assert gz.headers["cache-control"] == "public, max-age=31536000"
    assert "Accept-Encoding" in gz.headers["vary"]
    assert gz.content == raw.content
    assert int(gz.headers["content-length"]) < len(raw.content) // 2
    cached = app._gzip_static_cache["pywire.core.min.js"]
    assert gzip.decompress(cached[1]) == raw.content


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("text/html; charset=utf-8", True),
        ("application/javascript", True),
        ("application/x-msgpack", True),
        ("application/manifest+json", True),
        ("image/svg+xml", True),
        ("text/event-stream", False),
        ("image/png", False),
        ("font/woff2", False),
        ("", False),
    ],
)
def test_is_compressible(content_type: str, expected: bool) -> None:
    assert is_compressible(content_type) is expected


def _middleware_client() -> TestClient:
    async def big(request):
        return Response("x" * 5000, media_type="text/plain")

    async def small(request):
        return Response("tiny", media_type="text/plain")

    async def png(request):
        return Response(b"\x89PNG" + b"\0" * 5000, media_type="image/png")

    async def stream(request):
        async def chunks():
            for i in range(5):
                yield f"chunk {i} ".encode() * 200

        return StreamingResponse(chunks(), media_type="text/html")

    async def pre_encoded(request):
        body = gzip.compress(b"already" * 200)
        return Response(
            body, media_type="text/plain", headers={"Content-Encoding": "gzip"}
        )

    app = Starlette(
        routes=[
            Route("/big", big),
            Route("/small", small),
            Route("/png", png),
            Route("/stream", stream),
            Route("/pre", pre_encoded),
        ]
    )
    return TestClient(CompressionMiddleware(app))


def test_middleware_compresses_text_and_skips_the_rest() -> None:
    client = _middleware_client()

    big = client.get("/big", headers=GZIP)
    assert big.headers["content-encoding"] == "gzip"
    assert big.text == "x" * 5000

    small = client.get("/small", headers=GZIP)
    assert "content-encoding" not in small.headers
    assert small.text == "tiny"

    png = client.get("/png", headers=GZIP)
    assert "content-encoding" not in png.headers
    assert len(png.content) == 5004

    pre = client.get("/pre", headers=GZIP)
    assert pre.headers["content-encoding"] == "gzip"
    assert pre.content == b"already" * 200


def test_middleware_compresses_streams_chunk_by_chunk() -> None:
    response = _middleware_client().get("/stream", headers=GZIP)

    assert response.headers["content-encoding"] == "gzip"
    assert "content-length" not in response.headers
    assert response.text == "".join(f"chunk {i} " * 200 for i in range(5))


def test_relocate_replay_does_not_ask_for_compression() -> None:
    from unittest.mock import MagicMock

    from pywire.runtime.websocket import WebSocketHandler

    ws = MagicMock()
    ws.scope = {
        "headers": [
            (b"accept-encoding", b"gzip, deflate, br"),
            (b"user-agent", b"test"),
        ]
    }
    headers = WebSocketHandler(MagicMock())._build_internal_headers(ws, {})

    assert "accept-encoding" not in headers
    assert headers["user-agent"] == "test"
