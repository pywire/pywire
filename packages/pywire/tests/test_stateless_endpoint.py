"""Stateless (client-held state) mode: config, snapshot embedding, POST endpoint."""

import base64
import json
from pathlib import Path

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire

FIXTURE_PAGES = Path(__file__).parent / "fixtures" / "stateless_app" / "pages"
SECRET = "test-secret-key"

_MSGPACK = {"Content-Type": "application/x-msgpack"}


@pytest.fixture()
def client():
    app = PyWire(pages_dir=str(FIXTURE_PAGES), stateless=True, secret_key=SECRET)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _blob(html: str) -> str:
    return html.split('_pywire_snapshot" type="text/plain">')[1].split("</script>")[0]


def _post(client, blob: str, path: str = "/", handler: str = "increment"):
    return client.post(
        "/_pywire/stateless",
        content=msgpack.packb(
            {"path": path, "handler": handler, "data": {}, "snapshot": blob}
        ),
        headers=_MSGPACK,
    )


def test_missing_secret_raises(monkeypatch):
    monkeypatch.delenv("PYWIRE_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="PYWIRE_SECRET_KEY"):
        PyWire(pages_dir=str(FIXTURE_PAGES), stateless=True)


def test_secret_from_env(monkeypatch):
    monkeypatch.setenv("PYWIRE_SECRET_KEY", "env-secret")
    app = PyWire(pages_dir=str(FIXTURE_PAGES), stateless=True)
    assert app._stateless_secret == b"env-secret"
    assert app.state.stateless is True


def test_stateless_skips_ws_and_session_routes():
    app = PyWire(pages_dir=str(FIXTURE_PAGES), stateless=True, secret_key=SECRET)
    paths = {getattr(r, "path", None) for r in app.app.routes}
    assert "/_pywire/stateless" in paths
    for absent in (
        "/_pywire/ws",
        "/_pywire/session",
        "/_pywire/poll",
        "/_pywire/event",
    ):
        assert absent not in paths


def test_get_embeds_snapshot_without_secrets(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "_pywire_snapshot" in r.text
    assert "sk-hidden" not in r.text


def test_spa_meta_flags_stateless(client):
    r = client.get("/")
    meta = r.text.split('_pywire_spa_meta" type="application/json">')[1].split(
        "</script>"
    )[0]
    assert json.loads(meta)["stateless"] is True


def test_event_round_trip(client):
    blob = _blob(client.get("/").text)
    r = _post(client, blob)
    assert r.status_code == 200
    msg = msgpack.unpackb(r.content, raw=False)
    assert msg["snapshot"] != blob
    assert any("1" in reg["html"] for reg in msg.get("regions", []))
    assert msg["meta"]["pending_awaits"] == 0


def test_tampered_snapshot_400(client):
    raw = bytearray(base64.urlsafe_b64decode(_blob(client.get("/").text)))
    raw[-1] ^= 0xFF
    r = _post(client, base64.urlsafe_b64encode(bytes(raw)).decode())
    assert r.status_code == 400


def test_user_never_restored_from_client(client):
    snap = msgpack.unpackb(
        base64.urlsafe_b64decode(_blob(client.get("/").text))[32:], raw=False
    )
    assert "user" not in snap


def test_unknown_path_404(client):
    blob = _blob(client.get("/").text)
    r = _post(client, blob, path="/nope")
    assert r.status_code == 404


def test_endpoint_rejects_unlisted_handler(client):
    # "render" exists on every page but is not a registered event handler
    blob = _blob(client.get("/").text)
    r = _post(client, blob, handler="render")
    assert r.status_code == 400


def test_malformed_body_400(client):
    r = client.post("/_pywire/stateless", content=b"not msgpack", headers=_MSGPACK)
    assert r.status_code == 400
