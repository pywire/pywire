"""OneShotASGIAdapter: the one-shot (FaaS) integration surface.

Binding contract for every FaaS deploy target: `fetch()` is binary-safe and
returns (status, headers, body: bytes).
"""

import subprocess
import sys
from pathlib import Path

import msgpack
import pytest

from pywire.adapters.oneshot import OneShotASGIAdapter
from pywire.runtime.app import PyWire

FIXTURE_PAGES = Path(__file__).parent / "fixtures" / "stateless_app" / "pages"
SECRET = "test-secret-key-at-least-32-bytes"


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


@pytest.mark.asyncio
async def test_unhandled_error_returns_the_apps_500_page(tmp_path):
    # Starlette sends the app's 500 page and then re-raises. fetch() must
    # return that page: raising fails the whole FaaS invocation instead.
    (tmp_path / "index.wire").write_text(
        '---\n@init\ndef load():\n    raise RuntimeError("boom")\n---\n<p>x</p>\n'
    )
    app = PyWire(pages_dir=str(tmp_path), stateless=True, secret_key=SECRET)
    status, _, body = await OneShotASGIAdapter(app).fetch("GET", "/")
    assert status == 500
    assert body and b"boom" not in body  # no traceback outside debug mode


def test_stateless_app_boots_without_pywire_parser(tmp_path):
    # FaaS bundles install plain `pywire` (no [build] extra, so no parser)
    # and serve prebuilt pages; constructing the app must not need it.
    script = (
        "import sys\n"
        "sys.modules['pywire_parser'] = None  # importing it raises ImportError\n"
        "from pywire.runtime.app import PyWire\n"
        f"PyWire(pages_dir={str(tmp_path)!r}, stateless=True, secret_key='test-signing-key-0123456789abcdef')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
