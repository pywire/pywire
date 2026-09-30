"""Stateless (client-held state) mode: config, snapshot embedding, POST endpoint."""

import base64
import re
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire
from pywire.runtime.page import BasePage

FIXTURE_PAGES = Path(__file__).parent / "fixtures" / "stateless_app" / "pages"
SECRET = "test-secret-key-at-least-32-bytes"

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
    """A snapshot sealed the way the server seals one, issued now."""
    import time

    from pywire.runtime.snapshot_codec import sign

    stamped = {"iat": int(time.time()), **snapshot}
    return sign(stamped, secret=SECRET.encode())


def test_missing_secret_raises(monkeypatch):
    monkeypatch.delenv("PYWIRE_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="PYWIRE_SECRET_KEY"):
        PyWire(pages_dir=str(FIXTURE_PAGES), stateless=True)


@pytest.mark.parametrize(
    "secret",
    [
        "dev-only-insecure-fallback-key",
        "k" * 31,
        "k" * 64,
        "abab" * 16,
        "changeme-0123456789abcdefghijklmnop",
        "django-insecure-0123456789abcdefghijk",
    ],
)
def test_weak_secret_raises(monkeypatch, secret):
    monkeypatch.delenv("PYWIRE_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="at least 32 random bytes"):
        PyWire(pages_dir=str(FIXTURE_PAGES), stateless=True, secret_key=secret)
    monkeypatch.setenv("PYWIRE_SECRET_KEY", secret)
    with pytest.raises(RuntimeError, match="at least 32 random bytes"):
        PyWire(pages_dir=str(FIXTURE_PAGES), stateless=True)


def test_weak_session_secret_raises(monkeypatch):
    monkeypatch.setenv("PYWIRE_SESSION_SECRET", "x" * 40)
    with pytest.raises(RuntimeError, match="PYWIRE_SESSION_SECRET"):
        PyWire(pages_dir=str(FIXTURE_PAGES), interactive_server_mode=False)


def test_secret_from_env(monkeypatch):
    monkeypatch.setenv("PYWIRE_SECRET_KEY", "env-secret-at-least-32-bytes-long")
    app = PyWire(pages_dir=str(FIXTURE_PAGES), stateless=True)
    assert app._stateless_secret == b"env-secret-at-least-32-bytes-long"
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
    from pywire.runtime.snapshot_codec import verify

    snap = verify(_blob(client.get("/").text), secret=SECRET.encode())
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
<p id="r">{result}</p><button @click={rename}>rename</button>
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


@pytest.mark.parametrize("content_type", [None, "text/plain", "application/json"])
def test_cross_site_capable_content_types_refused(client, content_type):
    """A form or no-cors fetch can post text/plain without a preflight; a
    valid snapshot minted by an attacker must not ride the victim's cookies."""
    blob = _blob(client.get("/").text)
    body = msgpack.packb(
        {"path": "/", "handler": "increment", "data": {}, "snapshot": blob}
    )
    headers = {"Content-Type": content_type} if content_type else {}
    r = client.post("/_pywire/stateless", content=body, headers=headers)
    assert r.status_code == 415


@pytest.mark.parametrize(
    ("site", "status"),
    [("cross-site", 403), ("same-site", 403), ("same-origin", 200), ("none", 200)],
)
def test_sec_fetch_site_must_be_same_origin(client, site, status):
    blob = _blob(client.get("/").text)
    body = msgpack.packb(
        {"path": "/", "handler": "increment", "data": {}, "snapshot": blob}
    )
    r = client.post(
        "/_pywire/stateless",
        content=body,
        headers={
            "Content-Type": "application/x-msgpack; charset=binary",
            "Sec-Fetch-Site": site,
        },
    )
    assert r.status_code == status


@pytest.mark.parametrize(
    ("origin", "status"),
    [("https://evil.example", 403), ("null", 403), ("http://testserver", 200)],
)
def test_origin_checked_without_sec_fetch_site(client, origin, status):
    """Browsers without Sec-Fetch-Site still send Origin on a POST."""
    blob = _blob(client.get("/").text)
    body = msgpack.packb(
        {"path": "/", "handler": "increment", "data": {}, "snapshot": blob}
    )
    r = client.post(
        "/_pywire/stateless", content=body, headers={**_MSGPACK, "Origin": origin}
    )
    assert r.status_code == status


def test_streamed_body_is_capped_as_it_arrives(client, monkeypatch):
    """A chunked body declares no length; the cap counts what arrives."""
    monkeypatch.setattr("pywire.runtime.stateless_handler.MAX_BODY_LEN", 1000)

    def chunks():
        for _ in range(10):
            yield b"x" * 500

    r = client.post("/_pywire/stateless", content=chunks(), headers=_MSGPACK)
    assert r.status_code == 413


def test_frontmatter_constants_stay_out_of_the_snapshot(tmp_path):
    from pywire.runtime.snapshot_codec import verify

    (tmp_path / "index.wire").write_text(
        "---\n"
        'API_KEY = "sk_live_must_not_leak"\n'
        "picked = ''\n"
        "count = wire(0)\n\n"
        "def pick():\n"
        "    self.picked = 'row-3'\n"
        "    count.value += 1\n"
        "---\n"
        "<p>{count}</p><button @click={pick}>go</button>\n"
    )
    app = PyWire(pages_dir=str(tmp_path), stateless=True, secret_key=SECRET)
    with TestClient(app) as c:
        html = c.get("/").text
        snap = verify(_blob(html), secret=SECRET.encode())
        assert "API_KEY" not in snap["attrs"] and "sk_live" not in str(snap)
        r = _post(c, _blob(html), handler="pick")
        assert r.status_code == 200
        blob = msgpack.unpackb(r.content, raw=False)["snapshot"]
        snap = verify(blob, secret=SECRET.encode())
        assert "API_KEY" not in snap["attrs"]
        assert snap["attrs"]["picked"] == "row-3"
        # The carried value survives the next rebuild.
        r = _post(c, blob, handler="pick")
        assert (
            verify(
                msgpack.unpackb(r.content, raw=False)["snapshot"],
                secret=SECRET.encode(),
            )["attrs"]["count"]
            == 2
        )


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
