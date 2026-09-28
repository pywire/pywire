"""Stateless (client-held state) mode: config, snapshot embedding, POST endpoint."""

import base64
import hashlib
import hmac
import re
import zlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire
from pywire.runtime.page import BasePage

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


def _post(client, blob: str, path: str = "/", handler: str = "increment", data=None):
    return client.post(
        "/_pywire/stateless",
        content=msgpack.packb(
            {
                "path": path,
                "handler": handler,
                "data": {} if data is None else data,
                "snapshot": blob,
            }
        ),
        headers=_MSGPACK,
    )


def _error(r) -> str:
    return msgpack.unpackb(r.content, raw=False)["error"]


def _sign(snapshot: dict) -> str:
    body = zlib.compress(msgpack.packb(snapshot))
    sig = hmac.new(SECRET.encode(), body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig + body).decode("ascii")


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


@pytest.mark.asyncio
async def test_stateless_rejects_webtransport_scope():
    # WebTransport bypasses the route list AND the middleware stack — the
    # handler must never be created, and the scope falls through to Starlette.
    app = PyWire(pages_dir=str(FIXTURE_PAGES), stateless=True, secret_key=SECRET)
    assert app.web_transport_handler is None
    with patch.object(app, "app", new_callable=AsyncMock) as mock_starlette:
        await app({"type": "webtransport"}, AsyncMock(), AsyncMock())
        mock_starlette.assert_called_once()


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


def test_tampered_snapshot_400(client):
    raw = bytearray(base64.urlsafe_b64decode(_blob(client.get("/").text)))
    raw[-1] ^= 0xFF
    r = _post(client, base64.urlsafe_b64encode(bytes(raw)).decode())
    assert r.status_code == 400
    assert _error(r) == "invalid snapshot"


def test_user_never_restored_from_client(client):
    body = base64.urlsafe_b64decode(_blob(client.get("/").text))[32:]
    snap = msgpack.unpackb(zlib.decompress(body), raw=False)
    assert "user" not in snap


def test_unknown_path_404(client):
    blob = _sign({"attrs": {}, "route": "/nope"})
    r = _post(client, blob, path="/nope")
    assert r.status_code == 404
    assert _error(r) == "no route"


def test_snapshot_bound_to_its_path(client):
    # A snapshot rendered for "/" must not rebuild "/boom": that page's
    # @before_load/@init hooks never run on events, so a transplanted
    # snapshot would reach its handlers without their checks.
    blob = _blob(client.get("/").text)
    r = _post(client, blob, path="/boom", handler="explode")
    assert r.status_code == 400
    assert _error(r) == "invalid snapshot"


def test_snapshot_bound_to_its_query(client):
    blob = _blob(client.get("/?tab=a").text)
    assert _post(client, blob, path="/?tab=b").status_code == 400
    r = _post(client, blob, path="/?tab=a")
    assert r.status_code == 200
    # The next snapshot stays bound to the same URL.
    nxt = msgpack.unpackb(r.content, raw=False)["snapshot"]
    assert _post(client, nxt, path="/?tab=a").status_code == 200
    assert _post(client, nxt, path="/").status_code == 400


def test_unsigned_route_rejected(client):
    # Pre-binding snapshots (no route) are refused like any foreign blob.
    blob = _sign({"attrs": {}})
    r = _post(client, blob, path="/")
    assert r.status_code == 400
    assert _error(r) == "invalid snapshot"


BEFORE_LOAD_GUARD = """---
result = wire("")

@before_load
def authorize():
    if org_id != "1":
        raise PermissionError("not a member of this org")

def rename():
    result.value = f"renamed org {org_id}"
---
<p id="r">{result}</p><button @click={rename()}>rename</button>
"""


def test_transplant_cannot_skip_before_load(tmp_path):
    pages = tmp_path / "pages"
    (pages / "orgs").mkdir(parents=True)
    (pages / "orgs" / "[org_id].wire").write_text(BEFORE_LOAD_GUARD)
    (pages / "index.wire").write_text("<p>home</p>")
    app = PyWire(pages_dir=str(pages), stateless=True, secret_key=SECRET)
    with TestClient(app, raise_server_exceptions=False) as c:
        assert c.get("/orgs/2").status_code == 500  # @before_load refuses

        for source in ("/", "/orgs/1"):
            blob = _blob(c.get(source).text)
            r = _post(c, blob, path="/orgs/2", handler="rename")
            assert r.status_code == 400, source
            assert _error(r) == "invalid snapshot"

        blob = _blob(c.get("/orgs/1").text)
        r = _post(c, blob, path="/orgs/1", handler="rename")
        assert r.status_code == 200
        html = "".join(reg["html"] for reg in msgpack.unpackb(r.content)["regions"])
        assert "renamed org 1" in html


def test_non_string_path_400(client):
    # Forged msgpack int path must not reach urlparse() as a 500
    blob = _blob(client.get("/").text)
    r = _post(client, blob, path=42)
    assert r.status_code == 400
    assert _error(r) == "invalid path"


def test_non_dict_event_data_400(client):
    # Forged msgpack int data must not die mid-dispatch as a 500
    blob = _blob(client.get("/").text)
    r = _post(client, blob, data=42)
    assert r.status_code == 400
    assert _error(r) == "invalid data"


@pytest.mark.parametrize("snap", [42, ["x"], {"a": 1}, None])
def test_non_str_snapshot_400(client, snap):
    # Forged non-str snapshot must be a clean 400 before decode
    # (blob.encode("ascii") raised AttributeError -> 500), not a crash.
    r = client.post(
        "/_pywire/stateless",
        content=msgpack.packb(
            {"path": "/", "handler": "", "data": {}, "snapshot": snap}
        ),
        headers=_MSGPACK,
    )
    assert r.status_code == 400
    assert _error(r) == "invalid snapshot"


def test_non_ascii_path_resolves_cleanly(client):
    # Deterministic outcome: router patterns are ASCII, so "/caf\u00e9" matches
    # no route and resolve_page returns None *before* the raw_path
    # ascii-encoding is reached \u2014 a clean 404, never a UnicodeEncodeError 500.
    blob = _sign({"attrs": {}, "route": "/caf\u00e9"})
    r = _post(client, blob, path="/caf\u00e9")
    assert r.status_code == 404
    assert _error(r) == "no route"


def test_endpoint_rejects_unlisted_handler(client):
    # "render" exists on every page but is not a registered event handler
    blob = _blob(client.get("/").text)
    r = _post(client, blob, handler="render")
    assert r.status_code == 400
    assert _error(r) == "invalid handler"


def test_handler_business_value_error_is_500(client):
    # A ValueError raised *inside* an allowlisted handler is a server fault:
    # it must hit the 500 path (with logger.exception), not masquerade as
    # a client-level "invalid handler" 400.
    blob = _blob(client.get("/boom").text)
    r = client.post(
        "/_pywire/stateless",
        content=msgpack.packb(
            {"path": "/boom", "handler": "explode", "data": {}, "snapshot": blob}
        ),
        headers=_MSGPACK,
    )
    assert r.status_code == 500
    assert _error(r) == "event failed"


def test_stateless_embedding_preserves_set_cookie():
    # page.render() applies pending cookies to the response it returns; the
    # snapshot embedding must mutate that response in place, not rebuild it.
    class CookiePage(BasePage):
        __route__ = "/cookie"

        async def _render_template(self):
            self.set_cookie("flavor", "choc")
            return "<html><body><p>cookie</p></body></html>"

    app = PyWire(pages_dir=str(FIXTURE_PAGES), stateless=True, secret_key=SECRET)
    app.router.add_route("/cookie", CookiePage)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/cookie")
    assert r.status_code == 200
    assert "_pywire_snapshot" in r.text
    assert "flavor=choc" in r.headers.get("set-cookie", "")


def test_malformed_body_400(client):
    r = client.post("/_pywire/stateless", content=b"not msgpack", headers=_MSGPACK)
    assert r.status_code == 400


def test_oversized_snapshot_rejected_without_decode(client, monkeypatch):
    """Oversized snapshot fields are refused before any base64/HMAC/msgpack
    work — otherwise a huge blob is a CPU/memory DoS vector."""
    from unittest.mock import MagicMock

    from pywire.runtime.snapshot_codec import MAX_SNAPSHOT_LEN

    mock = MagicMock(return_value={})
    monkeypatch.setattr("pywire.runtime.stateless_handler.decode_snapshot", mock)
    r = _post(client, "A" * (MAX_SNAPSHOT_LEN + 1))
    assert r.status_code == 413
    mock.assert_not_called()


def test_oversized_declared_content_length_rejected_before_body(client):
    """A declared Content-Length over the snapshot cap is refused before the
    body is read — defense in depth alongside the per-blob ceiling."""
    from pywire.runtime.snapshot_codec import MAX_SNAPSHOT_LEN

    r = client.post(
        "/_pywire/stateless",
        content=b"x",
        headers={**_MSGPACK, "Content-Length": str(MAX_SNAPSHOT_LEN + 2049)},
    )
    assert r.status_code == 413


NAV_COMPONENT = """---
n = wire(0)

def bump():
    n.value += 1
---
<button id="nav" @click={bump()}>nav {n}</button>
"""

NAV_LAYOUT = """---
from components.Nav import Nav
---
<html><body><Nav /><main>{$render children}</main></body></html>
"""


def test_nested_component_handler_dispatches(tmp_path, monkeypatch):
    # A component inside the layout is two levels deep:
    # _comp:<layout>:_comp:<Nav>:bump. The allowlist check must walk the
    # same chain handle_event dispatches through.
    pages = tmp_path / "pages"
    pages.mkdir()
    (tmp_path / "components").mkdir()
    (tmp_path / "components" / "Nav.wire").write_text(NAV_COMPONENT)
    (pages / "__layout__.wire").write_text(NAV_LAYOUT)
    (pages / "index.wire").write_text("<p>home</p>")
    monkeypatch.syspath_prepend(str(tmp_path))  # project root, as in a real app
    app = PyWire(pages_dir=str(pages), stateless=True, secret_key=SECRET)
    with TestClient(app, raise_server_exceptions=False) as c:
        html = c.get("/").text
        handler = re.search(r'id="nav"[^>]*data-on-click="([^"]+)"', html)[1]
        assert handler.count("_comp:") == 2, handler

        r = _post(c, _blob(html), handler=handler)
        assert r.status_code == 200, _error(r)

        prefix = handler.rsplit(":", 1)[0]
        r = _post(c, _blob(html), handler=f"{prefix}:render")
        assert r.status_code == 400
        assert _error(r) == "invalid handler"
