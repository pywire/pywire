"""Stateless mode: file uploads are plain HTTP and must work without WS (T27).

Uploads are not an interactive transport feature: the browser POSTs the
file to ``/_pywire/upload`` with the page-issued token, then the submit
carries the returned upload id and the handler gets an ``Upload``. Both
halves must work in a ``stateless=True`` app.
"""

from pathlib import Path

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire

FIXTURE_PAGES = Path(__file__).parent / "fixtures" / "stateless_app" / "pages"
SECRET = "test-secret-key-at-least-32-bytes"

_MSGPACK = {"Content-Type": "application/x-msgpack"}


@pytest.fixture()
def client():
    app = PyWire(pages_dir=str(FIXTURE_PAGES), stateless=True, secret_key=SECRET)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _token(html: str) -> str:
    return html.split('name="pywire-upload-token" content="')[1].split('"')[0]


def _blob(html: str) -> str:
    return html.split('_pywire_snapshot" type="text/plain">')[1].split("</script>")[0]


def test_upload_route_mounted_in_stateless_mode(client):
    paths = {getattr(r, "path", None) for r in client.app.app.routes}
    assert "/_pywire/upload" in paths


def test_upload_reaches_handler(client):
    r = client.get("/upload")
    assert r.status_code == 200
    token = _token(r.text)

    up = client.post(
        "/_pywire/upload",
        files={"doc": ("hello.txt", b"hello world", "text/plain")},
        headers={"X-Upload-Token": token},
    )
    assert up.status_code == 200
    (upload_id,) = up.json()["doc"]

    # The submit carries the id; the stateless handler gets the file.
    r = client.post(
        "/_pywire/stateless",
        content=msgpack.packb(
            {
                "path": "/upload",
                "handler": "save",
                "data": {
                    "type": "submit",
                    "formData": {"doc": {"_upload_id": upload_id}},
                },
                "snapshot": _blob(r.text),
            }
        ),
        headers=_MSGPACK,
    )
    assert r.status_code == 200
    msg = msgpack.unpackb(r.content, raw=False)
    assert any("hello.txt:hello world" in reg["html"] for reg in msg.get("regions", []))


def test_traversal_upload_token_cannot_delete_outside_dir(client):
    """X-Upload-Token path traversal must not delete ``*.json`` outside the
    token dir (``_token_file_path`` joined the raw header value)."""
    import json
    import os

    app = client.app
    probe_name = f"pywire_traversal_probe_{os.getpid()}"
    target = (app._upload_token_dir / ".." / ".." / f"{probe_name}.json").resolve()
    target.write_text(json.dumps({"session_id": None, "issued_ts": 0.0}))
    try:
        up = client.post(
            "/_pywire/upload",
            files={"doc": ("x.txt", b"x", "text/plain")},
            headers={"X-Upload-Token": f"../../{probe_name}"},
        )
        assert up.status_code == 403
        assert target.exists(), "traversal token deleted a file outside the token dir"
    finally:
        target.unlink(missing_ok=True)
