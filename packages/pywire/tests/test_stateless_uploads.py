"""Stateless mode: file uploads are plain HTTP and must work without WS (T27).

The kernel gap: uploads are not an interactive transport feature — the
browser POSTs the file to ``/_pywire/upload`` with the page-issued token,
then hands the returned upload id to the event handler. Both halves must
work in a ``stateless=True`` app.
"""

from pathlib import Path

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire
from pywire.runtime.upload_manager import upload_manager

FIXTURE_PAGES = Path(__file__).parent / "fixtures" / "stateless_app" / "pages"
SECRET = "test-secret-key"

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
    upload_id = up.json()["doc"]

    # The file landed in upload storage with its bytes intact.
    stored = upload_manager.get(upload_id)
    assert stored is not None
    assert stored.filename == "hello.txt"
    assert stored.content == b"hello world"

    # The upload id reaches the stateless event handler.
    r = client.post(
        "/_pywire/stateless",
        content=msgpack.packb(
            {
                "path": "/upload",
                "handler": "save",
                "data": {"doc": upload_id},
                "snapshot": _blob(r.text),
            }
        ),
        headers=_MSGPACK,
    )
    assert r.status_code == 200
    msg = msgpack.unpackb(r.content, raw=False)
    assert any(upload_id in reg["html"] for reg in msg.get("regions", []))
