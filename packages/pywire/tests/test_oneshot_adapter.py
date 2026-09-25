"""OneShotASGIAdapter: the one-shot (FaaS) integration surface.

Binding contract for every FaaS deploy target: `fetch()` is binary-safe and
returns (status, headers, body: bytes).
"""

from pathlib import Path

import msgpack
import pytest

from pywire.adapters.oneshot import OneShotASGIAdapter
from pywire.runtime.app import PyWire

FIXTURE_PAGES = Path(__file__).parent / "fixtures" / "stateless_app" / "pages"
SECRET = "test-secret-key"


@pytest.fixture()
def adapter():
    app = PyWire(pages_dir=str(FIXTURE_PAGES), stateless=True, secret_key=SECRET)
    return OneShotASGIAdapter(app)


def _blob(body: bytes) -> str:
    return (
        body.decode("utf-8")
        .split('_pywire_snapshot" type="text/plain">')[1]
        .split("</script>")[0]
    )


@pytest.mark.asyncio
async def test_get_returns_bytes_with_snapshot(adapter):
    status, headers, body = await adapter.fetch("GET", "/")
    assert status == 200
    assert isinstance(body, bytes)
    assert b"_pywire_snapshot" in body
    assert isinstance(headers, list)


@pytest.mark.asyncio
async def test_stateless_event_round_trip(adapter):
    status, _, body = await adapter.fetch("GET", "/")
    assert status == 200
    blob = _blob(body)
    status, _, resp = await adapter.fetch(
        "POST",
        "/_pywire/stateless",
        headers={"content-type": "application/x-msgpack"},
        body=msgpack.packb(
            {"path": "/", "handler": "increment", "data": {}, "snapshot": blob}
        ),
    )
    assert status == 200
    assert isinstance(resp, bytes)
    msg = msgpack.unpackb(resp, raw=False)  # binary body decodes to msgpack
    assert msg["snapshot"] != blob
    assert "regions" in msg
    assert any("1" in reg["html"] for reg in msg["regions"])


@pytest.mark.asyncio
async def test_binary_response_byte_identical():
    # Non-UTF-8 msgpack bytes must survive fetch() untouched — no decode,
    # no hex() fallback.
    payload = msgpack.packb({"b": b"\xff\xfe\x80\x00", "n": [1, 2, 3]})

    async def app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/x-msgpack")],
            }
        )
        await send({"type": "http.response.body", "body": payload})

    adapter = OneShotASGIAdapter(app)
    status, headers, body = await adapter.fetch("GET", "/msgpack")
    assert status == 200
    assert body == payload
    assert dict(headers)["content-type"] == "application/x-msgpack"
