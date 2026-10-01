"""Stateless events restore wire->region subscriptions from the snapshot
instead of rendering the page to discover them."""

import re
from pathlib import Path
from typing import Any, Dict, List

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.auth import ClaimsPrincipal
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

def drop():
    items.value.pop(0)
---
<h1>{title} ({len(items.value)})</h1>
<ul>
{$for idx, item in enumerate(items.value), key=idx}
    <li><span>{item["name"]}</span><span>{item["done"]}</span><button @click={toggle(idx)}>toggle</button></li>
{/for}
</ul>
<button id="rename" @click={rename}>rename</button>
<button id="add" @click={add}>add</button>
<button id="drop" @click={drop}>drop</button>
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


def _subs(app, blob: str) -> Dict[str, Any]:
    return decode_snapshot(blob, secret=app._stateless_secret)["subs"]


def _regions(msg: Dict[str, Any]) -> Dict[str, str]:
    return {reg["region"]: reg["html"] for reg in msg["regions"]}


def test_event_skips_discard_render_and_patches_one_row(tmp_path, renders):
    app = _app(tmp_path, list=LIST_PAGE)
    with TestClient(app, raise_server_exceptions=False) as client:
        html = client.get("/list").text
        blob = _blob(html)
        # One rule for the loop's 50 rows, not one entry per row.
        subs = _subs(app, blob)
        [[path, site, field]] = subs["rows"]
        assert (path, field) == (["items"], None)
        assert "each" not in subs
        assert all(len(entry[0]) == 1 for entry in subs["wires"])
        renders.clear()

        r = _post(client, "/list", _row_handler(html), blob, arg=3)

        assert r.status_code == 200
        assert renders == []
        msg = msgpack.unpackb(r.content, raw=False)
        assert list(_regions(msg)) == [f"{site}#3"]
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

        # The heading reads the list's length, so it re-renders like the
        # loop would; the rows stay as they were.
        r = _post(client, "/list", _handler_for(html, 'id="rename"'), blob)
        msg = msgpack.unpackb(r.content, raw=False)
        assert r.status_code == 200
        assert "renamed" in "".join(_regions(msg).values())
        assert _subs(app, msg["snapshot"])["rows"] == _subs(app, blob)["rows"]

        r = _post(client, "/list", _handler_for(html, 'id="add"'), msg["snapshot"])
        msg = msgpack.unpackb(r.content, raw=False)
        assert r.status_code == 200
        assert "new" in "".join(_regions(msg).values())
        assert renders == []

        # The added row is in the rule: toggling it patches only that row.
        r = _post(client, "/list", _row_handler(html), msg["snapshot"], arg=50)
        msg = msgpack.unpackb(r.content, raw=False)
        assert renders == []
        [(region, row_html)] = _regions(msg).items()
        assert region.endswith("#50") and "new" in row_html and "True" in row_html


def test_rows_shift_after_a_delete(tmp_path, renders):
    app = _app(tmp_path, list=LIST_PAGE)
    with TestClient(app, raise_server_exceptions=False) as client:
        html = client.get("/list").text
        renders.clear()

        r = _post(client, "/list", _handler_for(html, 'id="drop"'), _blob(html))
        msg = msgpack.unpackb(r.content, raw=False)
        assert r.status_code == 200
        assert "(49)" in "".join(_regions(msg).values())

        r = _post(client, "/list", _row_handler(html), msg["snapshot"], arg=3)
        msg = msgpack.unpackb(r.content, raw=False)
        assert renders == []
        [(region, row_html)] = _regions(msg).items()
        assert region.endswith("#3") and "item-4" in row_html and "True" in row_html


def test_skipped_update_after_a_reshape_drops_the_map(tmp_path):
    # The rows changed but never re-rendered, so no rule or entry describes
    # them: the next event renders to find out.
    app = _app(
        tmp_path,
        held=(
            "---\n"
            "items = wire([{'n': k} for k in range(5)])\n"
            "\n"
            "@before_update\n"
            "def hold():\n"
            "    return False\n"
            "\n"
            "def add():\n"
            "    items.value.append({'n': 5})\n"
            "---\n"
            "<div>{$for i, item in enumerate(items.value), key=i}<i>{item['n']}</i>{/for}</div>"
            '<button id="add" @click={add}>add</button>\n'
        ),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        html = client.get("/held").text
        assert _subs(app, _blob(html))["rows"]

        r = _post(client, "/held", _handler_for(html, 'id="add"'), _blob(html))

        assert r.status_code == 200
        snap = msgpack.unpackb(r.content, raw=False)["snapshot"]
        assert "subs" not in decode_snapshot(snap, secret=app._stateless_secret)


KEYED_BY_FIELD = """---
todos = wire([{"id": "t" + str(k), "name": "todo-" + str(k), "done": False, "meta": {"hits": 0}} for k in range(20)])

def toggle(tid):
    for todo in todos.value:
        if todo["id"] == tid:
            todo["done"] = not todo["done"]
            todo["meta"]["hits"] += 1
---
<ul>
{$for todo in todos.value, key=todo["id"]}
    <li>{todo["name"]} {todo["done"]} {todo["meta"]["hits"]}<button @click={toggle(todo["id"])}>t</button></li>
{/for}
</ul>
"""


def test_rows_keyed_by_a_field(tmp_path, renders):
    app = _app(tmp_path, todos=KEYED_BY_FIELD)
    with TestClient(app, raise_server_exceptions=False) as client:
        html = client.get("/todos").text
        blob = _blob(html)
        [[path, site, field]] = _subs(app, blob)["rows"]
        assert (path, field) == (["todos"], "id")
        handler = re.search(
            r'data-on-click="([^"]+)"[^>]*data-arg-0="&quot;t7&quot;"', html
        )[1]  # type: ignore[index]
        renders.clear()

        r = _post(client, "/todos", handler, blob, arg="t7")

        msg = msgpack.unpackb(r.content, raw=False)
        assert renders == []
        [(region, row_html)] = _regions(msg).items()
        assert region == f"{site}#t7"
        assert "todo-7 True 1" in row_html


NEIGHBOURS = """---
todos = wire([{"id": "t" + str(19 - k), "name": "todo-" + str(k), "done": False} for k in range(20)])

def toggle(tid):
    for todo in todos.value:
        if todo["id"] == tid:
            todo["done"] = not todo["done"]
---
<ul>
{$for k, todo in enumerate(todos.value), key=todo["id"]}
    <li>{todo["name"]} {todos.value[k - 1]["name"] if k else ""} {todo["done"]}<button @click={toggle(todo["id"])}>t</button></li>
{/for}
</ul>
"""


def test_rows_keyed_by_a_field_that_also_read_a_neighbour(tmp_path, renders):
    # Row k's region reads row k - 1 too, and ids run downwards, so the
    # first region naming row 0 is row 1's: its key is no field of row 0.
    app = _app(tmp_path, chain=NEIGHBOURS)
    with TestClient(app, raise_server_exceptions=False) as client:
        html = client.get("/chain").text
        blob = _blob(html)
        [[path, site, field]] = _subs(app, blob)["rows"]
        assert (path, field) == (["todos"], "id")
        handler = re.search(
            r'data-on-click="([^"]+)"[^>]*data-arg-0="&quot;t12&quot;"', html
        )[1]  # type: ignore[index]
        renders.clear()

        r = _post(client, "/chain", handler, blob, arg="t12")

        msg = msgpack.unpackb(r.content, raw=False)
        assert renders == []
        # Row 7 (t12) changed; row 8 (t11) shows row 7's name, which did not.
        assert sorted(_regions(msg)) == [f"{site}#t11", f"{site}#t12"]


def test_regions_reading_every_row(tmp_path, renders):
    # Sorting reads every row's name in the loop's region, and the count
    # reads every row's done flag: one each rule, not one entry per row.
    app = _app(
        tmp_path,
        sorted_todos=KEYED_BY_FIELD.replace(
            "todos.value, key=",
            'sorted(todos.value, key=lambda t: t["name"], reverse=True), key=',
        ).replace(
            "<ul>",
            '<p>{sum(1 for t in todos.value if t["done"])} done</p><ul>',
        ),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        html = client.get("/sorted_todos").text
        blob = _blob(html)
        subs = _subs(app, blob)
        [[path, regions]] = subs["each"]
        assert path == ["todos"] and len(regions) == 2
        assert all(len(entry[0]) == 1 for entry in subs["wires"])
        handler = re.search(
            r'data-on-click="([^"]+)"[^>]*data-arg-0="&quot;t7&quot;"', html
        )[1]  # type: ignore[index]
        renders.clear()

        r = _post(client, "/sorted_todos", handler, blob, arg="t7")

        msg = msgpack.unpackb(r.content, raw=False)
        assert renders == []
        assert "1 done" in "".join(_regions(msg).values())
        assert "todo-7 True 1" in "".join(_regions(msg).values())
        assert _subs(app, msg["snapshot"]) == subs


def test_rows_of_a_dict(tmp_path, renders):
    app = _app(
        tmp_path,
        rows=(
            "---\n"
            "rows = wire({k: {'n': 0} for k in 'abc'})\n"
            "\n"
            "def bump(k):\n"
            "    rows.value[k]['n'] += 1\n"
            "---\n"
            "<div>{$for k, row in rows.value.items(), key=k}"
            "<b>{k}={row['n']}</b><button @click={bump(k)}>+</button>{/for}</div>\n"
        ),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        html = client.get("/rows").text
        blob = _blob(html)
        [[path, site, field]] = _subs(app, blob)["rows"]
        assert (path, field) == (["rows"], None)
        handler = re.search(
            r'data-on-click="([^"]+)"[^>]*data-arg-0="&quot;b&quot;"', html
        )[1]  # type: ignore[index]
        renders.clear()

        r = _post(client, "/rows", handler, blob, arg="b")

        msg = msgpack.unpackb(r.content, raw=False)
        assert renders == []
        assert {k: "b=1" in v for k, v in _regions(msg).items()} == {f"{site}#b": True}


def test_wire_every_row_reads(tmp_path, renders):
    app = _app(
        tmp_path,
        pick=(
            "---\n"
            "items = wire([{'n': k} for k in range(30)])\n"
            "selected = wire(-1)\n"
            "\n"
            "def pick(i):\n"
            "    selected.value = i\n"
            "---\n"
            "<div>{$for i, item in enumerate(items.value), key=i}"
            "<p class={'on' if selected.value == i else 'off'}>{item['n']}"
            "<button @click={pick(i)}>pick</button></p>{/for}</div>\n"
        ),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        html = client.get("/pick").text
        blob = _blob(html)
        subs = _subs(app, blob)
        # "Every row reads selected" is one reference to the rule.
        assert [["selected"], "value", [], [0]] in subs["wires"]
        renders.clear()

        r = _post(client, "/pick", _row_handler(html), blob, arg=3)

        msg = msgpack.unpackb(r.content, raw=False)
        assert renders == []
        regions = _regions(msg)
        assert len(regions) == 30
        assert [k for k, v in regions.items() if 'class="on"' in v] == [
            f"{subs['rows'][0][1]}#3"
        ]
        assert _subs(app, msg["snapshot"]) == subs


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


COUNTING_LAYOUT = """---
self.visits = 0

def visit(self):
    self.visits += 1
---
<html><body><button id="visit" @click={visit}>{visits}</button><main>{$render children}</main></body></html>
"""


def test_page_under_a_layout_skips_the_render(tmp_path, renders):
    # The layout reads no wires, so skipping its render changes nothing; its
    # own events still render, and its state survives the events that don't.
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "__layout__.wire").write_text(COUNTING_LAYOUT)
    (pages / "list.wire").write_text(LIST_PAGE)
    app = PyWire(pages_dir=str(pages), stateless=True, secret_key=SECRET)
    with TestClient(app, raise_server_exceptions=False) as client:
        html = client.get("/list").text
        visit = _handler_for(html, 'id="visit"')
        assert visit.startswith("_comp:")

        def visits(blob: str) -> Any:
            [layout] = decode_snapshot(blob, secret=app._stateless_secret)[
                "component_snapshots"
            ].values()
            return layout["visits"]["value"]

        r = _post(client, "/list", visit, _blob(html))
        blob = msgpack.unpackb(r.content, raw=False)["snapshot"]
        assert visits(blob) == 1
        renders.clear()

        r = _post(client, "/list", _row_handler(html), blob, arg=3)
        msg = msgpack.unpackb(r.content, raw=False)
        assert renders == []
        assert [k.endswith("#3") for k in _regions(msg)] == [True]
        assert visits(msg["snapshot"]) == 1

        r = _post(client, "/list", visit, msg["snapshot"])
        assert renders  # a component event builds its component
        assert visits(msgpack.unpackb(r.content, raw=False)["snapshot"]) == 2


def test_edited_page_source_renders_once(tmp_path, renders):
    # A deploy can renumber the page's regions: a map from before it would
    # dirty the wrong ones.
    app = _app(tmp_path, list=LIST_PAGE)
    with TestClient(app, raise_server_exceptions=False) as client:
        html = client.get("/list").text
        (tmp_path / "pages" / "list.wire").write_text(LIST_PAGE + "<footer></footer>\n")
        renders.clear()

        r = _post(client, "/list", _row_handler(html), _blob(html), arg=3)

        assert r.status_code == 200
        assert renders


def test_stale_subscription_map_falls_back_to_render(tmp_path, renders):
    app = _app(tmp_path, list=LIST_PAGE)
    with TestClient(app, raise_server_exceptions=False) as client:
        html = client.get("/list").text
        snap = decode_snapshot(_blob(html), secret=app._stateless_secret)
        # A map naming a row the restored list no longer has (a deploy
        # changed the page) must not 500: the endpoint renders instead.
        snap["subs"] = {"wires": [[["items", 999], "value", ["r#999"]]]}
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
