"""Debug snapshot inspector (T27): GET /_pywire/debug/snapshot?blob=...

Debug-mode-only endpoint that decodes + verifies a client-held snapshot
and pretty-prints the page state. The HMAC gate stays in front: a tampered
blob is a 4xx, never a decode. The signing secret is never echoed.
"""

import asyncio
import base64
from pathlib import Path

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire

FIXTURE_PAGES = Path(__file__).parent / "fixtures" / "stateless_app" / "pages"
SECRET = "test-secret-key"

_MSGPACK = {"Content-Type": "application/x-msgpack"}


def _app(debug: bool, dev: bool = True) -> PyWire:
    app = PyWire(
        pages_dir=str(FIXTURE_PAGES), stateless=True, secret_key=SECRET, debug=debug
    )
    # dev_server.py flips this at startup; the inspector must be a no-op
    # without it even when debug=True ('pywire run' exposure).
    if dev:
        app._is_dev_mode = True
    return app


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


def test_debug_on_prod_mode_404():
    """debug=True outside dev mode must not expose the inspector — matches
    the _is_dev_mode gate on _handle_source/_handle_file/_handle_devtools_json."""
    with TestClient(_app(debug=True, dev=False), raise_server_exceptions=False) as c:
        blob = _blob(c.get("/").text)
        r = c.get("/_pywire/debug/snapshot", params={"blob": blob})
        assert r.status_code == 404


def test_oversized_blob_rejected_without_decode(monkeypatch):
    """A multi-MB blob must be refused before base64/HMAC/msgpack decode.

    Called directly on the handler: httpx caps query-string length, so a
    4MB URL cannot go through TestClient.
    """
    from unittest.mock import MagicMock

    from pywire.runtime.snapshot_codec import MAX_SNAPSHOT_LEN

    mock = MagicMock(return_value={})
    monkeypatch.setattr("pywire.runtime.snapshot_codec.decode_snapshot", mock)
    app = _app(debug=True)
    request = MagicMock()
    request.query_params = {"blob": "A" * (MAX_SNAPSHOT_LEN + 1)}
    r = asyncio.run(app._handle_debug_snapshot(request))
    assert r.status_code == 413
    mock.assert_not_called()


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
