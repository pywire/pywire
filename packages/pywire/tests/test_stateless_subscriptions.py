"""Stateless events restore wire->region subscriptions from the snapshot
instead of rendering the page to discover them."""

import re
from pathlib import Path
from typing import Any, Dict, List

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.auth import Claim, ClaimsPrincipal
from pywire.runtime.app import PyWire
from pywire.runtime.snapshot_codec import decode_snapshot, sign

SECRET = "test-secret-key-at-least-32-bytes"

LIST_PAGE = """---
items = wire([{"name": "item-" + str(k), "done": False} for k in range(50)])
title = wire("todo")

def toggle(i):
    items.value[i]["done"] = not items.value[i]["done"]

def rename():
    title.value = "renamed"

def add():
    items.value.append({"name": "new", "done": False})
---
<h1>{title}</h1>
<ul>
{$for idx, item in enumerate(items.value), key=idx}
    <li><span>{item["name"]}</span><span>{item["done"]}</span><button @click={toggle(idx)}>toggle</button></li>
{/for}
</ul>
<button id="rename" @click={rename}>rename</button>
<button id="add" @click={add}>add</button>
"""

SHARED_MODULE = "shared_subs_test_state"

SHARED_PAGE = """---
from shared_subs_test_state import hits

count = wire(0)

def bump():
    count.value += 1
---
<p>{hits.value}</p><p>{count}</p><button @click={bump}>+</button>
"""

PROTECTED_PAGE = """!auth
---
count = wire(0)

def bump():
    count.value += 1
---
<p>{count}</p><button @click={bump}>+</button>
"""

ADMIN = ClaimsPrincipal(is_authenticated=True, name="a", user_id="x:1", claims=[])
_PRINCIPAL: Dict[str, Any] = {"value": ADMIN}


class _AuthApp(PyWire):
    def get_user(self, request):
        return _PRINCIPAL["value"]


def _app(tmp_path: Path, cls=PyWire, **pages: str):
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    for name, src in pages.items():
        (pages_dir / f"{name}.wire").write_text(src)
    return cls(
        pages_dir=str(pages_dir),
        stateless=True,
        secret_key=SECRET,
        interactive_server_mode=False,
    )


def _blob(html: str) -> str:
    return html.split('_pywire_snapshot" type="text/plain">')[1].split("</script>")[0]


def _handler_for(html: str, marker: str) -> str:
    m = re.search(rf'{marker}[^>]*data-on-click="([^"]+)"', html) or re.search(
        rf'data-on-click="([^"]+)"[^>]*{marker}', html
    )
    assert m, marker
    return m.group(1)


def _post(client, path: str, handler: str, blob: str, arg=None):
    data: Dict[str, Any] = {"type": "click", "tagName": "BUTTON"}
    if arg is not None:
        data["args"] = {"arg0": arg}
    return client.post(
        "/_pywire/stateless",
        content=msgpack.packb(
            {"path": path, "handler": handler, "data": data, "snapshot": blob}
        ),
        headers={"Content-Type": "application/x-msgpack"},
    )


@pytest.fixture()
def renders(monkeypatch) -> List[str]:
    """Class names of pages rendered through ``BasePage.render``."""
    # Looked up now: other tests reload pywire.runtime.page, so an import at
    # module level can be a stale class no loaded page derives from.
    from pywire.runtime.page import BasePage

    seen: List[str] = []
    original = BasePage.render

    async def spy(self, *args, **kwargs):
        seen.append(type(self).__name__)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(BasePage, "render", spy)
    return seen


def _row_handler(html: str) -> str:
    return re.search(r'data-on-click="([^"]+)"[^>]*data-arg-0="3"', html, re.S).group(1)  # type: ignore[union-attr]


def test_event_skips_discard_render_and_patches_one_row(tmp_path, renders):
    app = _app(tmp_path, list=LIST_PAGE)
    with TestClient(app, raise_server_exceptions=False) as client:
        html = client.get("/list").text
        blob = _blob(html)
        assert "subs" in decode_snapshot(blob, secret=app._stateless_secret)
        renders.clear()

        r = _post(client, "/list", _row_handler(html), blob, arg=3)

        assert r.status_code == 200
        assert renders == []
        msg = msgpack.unpackb(r.content, raw=False)
        assert [reg["region"].endswith("#3") for reg in msg["regions"]] == [True]
        assert "True" in msg["regions"][0]["html"]

        # The returned snapshot carries the map again: chain another event.
        r2 = _post(client, "/list", _row_handler(html), msg["snapshot"], arg=3)
        msg2 = msgpack.unpackb(r2.content, raw=False)
        assert renders == []
        assert "False" in msg2["regions"][0]["html"]


def test_plain_wire_and_structural_change(tmp_path, renders):
    app = _app(tmp_path, list=LIST_PAGE)
    with TestClient(app, raise_server_exceptions=False) as client:
        html = client.get("/list").text
        blob = _blob(html)
        renders.clear()

        r = _post(client, "/list", _handler_for(html, 'id="rename"'), blob)
        msg = msgpack.unpackb(r.content, raw=False)
        assert r.status_code == 200
        assert "renamed" in "".join(reg["html"] for reg in msg["regions"])

        r = _post(client, "/list", _handler_for(html, 'id="add"'), blob)
        msg = msgpack.unpackb(r.content, raw=False)
        assert r.status_code == 200
        assert "new" in msg.get("html", "") + "".join(
            reg["html"] for reg in msg.get("regions", [])
        )
        # The added row is toggleable on the next event.
        subs = decode_snapshot(msg["snapshot"], secret=app._stateless_secret)["subs"]
        assert any(path == ["items", 50] for path, _f, _r in subs)


def test_page_reading_shared_state_keeps_discard_render(tmp_path, monkeypatch):
    mod = tmp_path / f"{SHARED_MODULE}.py"
    mod.write_text("from pywire import wire\nhits = wire(0)\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    app = _app(tmp_path, shared=SHARED_PAGE)
    with TestClient(app, raise_server_exceptions=False) as client:
        blob = _blob(client.get("/shared").text)
        assert "subs" not in decode_snapshot(blob, secret=app._stateless_secret)


NAV_COMPONENT = """---
n = wire(0)

def bump():
    n.value += 1
---
<button id="nav" @click={bump()}>nav {n}</button>
"""

NAV_LAYOUT = """<html><body><Nav /><main>{$render children}</main></body></html>"""


def test_page_with_components_keeps_discard_render(tmp_path, monkeypatch, renders):
    pages = tmp_path / "pages"
    pages.mkdir()
    (tmp_path / "components").mkdir()
    (tmp_path / "components" / "Nav.wire").write_text(NAV_COMPONENT)
    (pages / "__layout__.wire").write_text(
        "---\nfrom components.Nav import Nav\n---\n" + NAV_LAYOUT
    )
    (pages / "index.wire").write_text("<p>home</p>")
    monkeypatch.syspath_prepend(str(tmp_path))
    app = PyWire(pages_dir=str(pages), stateless=True, secret_key=SECRET)
    with TestClient(app, raise_server_exceptions=False) as client:
        html = client.get("/").text
        blob = _blob(html)
        assert "subs" not in decode_snapshot(blob, secret=app._stateless_secret)
        handler = re.search(r'id="nav"[^>]*data-on-click="([^"]+)"', html)[1]  # type: ignore[index]
        renders.clear()

        r = _post(client, "/", handler, blob)

        assert r.status_code == 200
        assert renders  # the discard render still runs


def test_stale_subscription_map_falls_back_to_render(tmp_path, renders):
    app = _app(tmp_path, list=LIST_PAGE)
    with TestClient(app, raise_server_exceptions=False) as client:
        html = client.get("/list").text
        snap = decode_snapshot(_blob(html), secret=app._stateless_secret)
        # A map naming a row the restored list no longer has (a deploy
        # changed the page) must not 500: the endpoint renders instead.
        snap["subs"] = [[["items", 999], "value", ["r#999"]]]
        renders.clear()

        r = _post(
            client,
            "/list",
            _row_handler(html),
            sign(snap, secret=app._stateless_secret),
            arg=3,
        )

        assert r.status_code == 200
        assert renders  # the discard render still runs
        msg = msgpack.unpackb(r.content, raw=False)
        assert "True" in "".join(reg["html"] for reg in msg["regions"])


def test_fast_path_still_enforces_page_auth(tmp_path, renders):
    _PRINCIPAL["value"] = ADMIN
    app = _app(tmp_path, cls=_AuthApp, guarded=PROTECTED_PAGE)
    with TestClient(app, raise_server_exceptions=False) as client:
        html = client.get("/guarded").text
        blob = _blob(html)
        handler = _handler_for(html, "")
        assert "subs" in decode_snapshot(blob, secret=app._stateless_secret)

        _PRINCIPAL["value"] = ClaimsPrincipal(is_authenticated=False, name="")
        renders.clear()
        r = _post(client, "/guarded", handler, blob)

        msg = msgpack.unpackb(r.content, raw=False)
        assert msg.get("type") == "navigate"
        assert renders == []


def test_page_reading_a_wire_the_snapshot_skips_keeps_discard_render(tmp_path):
    # A wire whose value the snapshot can't serialize is rebuilt by the
    # frontmatter, not the snapshot, so an address into it could name a
    # different row on the next request.
    app = _app(
        tmp_path,
        opaque=(
            "---\n"
            "rows = wire([{'n': k, 'handle': object()} for k in range(3)])\n"
            "count = wire(0)\n"
            "---\n"
            "{$for row in rows.value, key=row['n']}<i>{row['n']}</i>{/for}"
            "<p>{count}</p>\n"
        ),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/opaque")
        assert r.status_code == 200
        snap = decode_snapshot(_blob(r.text), secret=app._stateless_secret)
        assert "rows" not in snap["attrs"]
        assert "subs" not in snap
