"""Debug snapshot inspector (T27): GET /_pywire/debug/snapshot?blob=...

Debug-mode-only endpoint that decodes + verifies a client-held snapshot
and pretty-prints the page state. The HMAC gate stays in front: a tampered
blob is a 4xx, never a decode. The signing secret is never echoed.
"""

import base64
from pathlib import Path

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire

FIXTURE_PAGES = Path(__file__).parent / "fixtures" / "stateless_app" / "pages"
SECRET = "test-secret-key"

_MSGPACK = {"Content-Type": "application/x-msgpack"}


def _app(debug: bool) -> PyWire:
    return PyWire(
        pages_dir=str(FIXTURE_PAGES), stateless=True, secret_key=SECRET, debug=debug
    )


def _blob(html: str) -> str:
    return html.split('_pywire_snapshot" type="text/plain">')[1].split("</script>")[0]


def _raw_state(blob: str) -> dict:
    return msgpack.unpackb(base64.urlsafe_b64decode(blob)[32:], raw=False)


def test_debug_on_returns_decoded_client_snapshot():
    with TestClient(_app(debug=True), raise_server_exceptions=False) as c:
        blob = _blob(c.get("/").text)
        # The client sends this blob back on the event POST …
        r = c.post(
            "/_pywire/stateless",
            content=msgpack.packb(
                {"path": "/", "handler": "increment", "data": {}, "snapshot": blob}
            ),
            headers=_MSGPACK,
        )
        assert r.status_code == 200

        # … and the inspector decodes exactly that state.
        got = c.get("/_pywire/debug/snapshot", params={"blob": blob})
        assert got.status_code == 200
        state = got.json()
        assert state == _raw_state(blob)
        assert state["attrs"]["count"] == 0
        # Locked wires stay out of client-held snapshots.
        assert "api_key" not in state["attrs"]
        # The secret is never echoed.
        assert SECRET not in got.text


def test_debug_off_404():
    with TestClient(_app(debug=False), raise_server_exceptions=False) as c:
        r = c.get("/_pywire/debug/snapshot", params={"blob": "AAAA"})
        assert r.status_code == 404


def test_tampered_blob_4xx():
    with TestClient(_app(debug=True), raise_server_exceptions=False) as c:
        raw = bytearray(base64.urlsafe_b64decode(_blob(c.get("/").text)))
        raw[-1] ^= 0xFF
        r = c.get(
            "/_pywire/debug/snapshot",
            params={"blob": base64.urlsafe_b64encode(bytes(raw)).decode()},
        )
        assert 400 <= r.status_code < 500


def test_missing_blob_400():
    with TestClient(_app(debug=True), raise_server_exceptions=False) as c:
        r = c.get("/_pywire/debug/snapshot")
        assert r.status_code == 400
