"""Task 13: keyed-region payload acceptance (Spec #6).

Pins the headline claim: toggling ONE row of a 1000-row keyed list ships a
tiny (<= 1 KB) regions payload — not the whole loop — through BOTH the
in-process/WS path and the stateless POST path (transport parity).

Event dispatch mirrors the REAL client shape: the button carries
``data-on-click="_handler_N"`` and ``data-arg-0="500"``; the client
(events/handler.ts getArgs) JSON-parses dataset ``arg*`` keys and sends
``{"type": "click", "tagName": "BUTTON", "args": {"arg0": 500}}``.
(Same shape as tests/test_wire_primitive.py's ``_handler_0`` dispatch.)

The keyless contrast test proves the bound is pinned by ``key=``: without
it, one toggle dirties the whole-loop region (~150 KB) and fails <= 1024.
"""

import json
import re
from types import SimpleNamespace

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire
from pywire.runtime.loader import PageLoader

N_ROWS = 1000
PAYLOAD_BOUND = 1024

# NOTE: the comprehension var is `k`, not `i` — frontmatter comprehensions
# leak their loop var as a page attribute, which would shadow toggle's `i`.
_PAGE_SRC = """---
items = wire([{"name": "item-" + str(k), "done": False} for k in range(1000)])

def toggle(i):
    items.value[i]["done"] = not items.value[i]["done"]

def add_row():
    items.value.append({"name": "new-row", "done": False})
---
<ul id="rows">
{$for idx, item in enumerate(items.value)KEYCLAUSE}
    <li><span>{item["name"]}</span><span>{item["done"]}</span><button @click={toggle(idx)}>toggle</button></li>
{/for}
</ul>
<button id="add" @click={add_row()}>add</button>
"""


def _src(keyed: bool) -> str:
    return _PAGE_SRC.replace("KEYCLAUSE", ", key=idx" if keyed else "")


def _make_page(tmp_path, source, name="page.wire"):
    file_path = tmp_path / name
    file_path.write_text(source)
    cls = PageLoader().load(file_path, use_cache=False)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(sibling_paths=[], enable_pjax=False, debug=False)
        )
    )
    return cls(request, {}, {}, {}, None)


def _row500_dispatch(html: str) -> tuple[str, dict]:
    """Extract (handler, event_data) for row 500's button exactly like the
    client does: data-on-click -> handler name, data-arg-0 -> args.arg0."""
    m = re.search(
        r'data-pw-region="[^"]+#500"[^>]*>.*?data-on-click="([^"]+)"[^>]*'
        r'data-arg-0="([^"]+)"',
        html,
        re.S,
    )
    assert m, "row-500 keyed wrapper with toggle button not found in render"
    return m.group(1), {
        "type": "click",
        "tagName": "BUTTON",
        "args": {"arg0": json.loads(m.group(2))},
    }


def _assert_single_tiny_row500(update: dict, site: str) -> int:
    assert update["type"] == "regions"
    regions = update["regions"]
    assert len(regions) == 1
    assert regions[0]["region"] == f"{site}#500"
    assert "item-500" in regions[0]["html"]
    total = sum(len(r["html"]) for r in regions)
    assert total <= PAYLOAD_BOUND, f"payload {total} B exceeds {PAYLOAD_BOUND} B"
    return total


@pytest.mark.asyncio
async def test_single_toggle_payload_in_process(tmp_path):
    """1000-row keyed page: one toggle event -> ONE #500 region, <= 1 KB."""
    page = _make_page(tmp_path, _src(keyed=True))
    html = await page._render_template()
    site = next(iter(page.__keyed_region_renderers__))
    handler, event_data = _row500_dispatch(html)
    assert event_data["args"]["arg0"] == 500

    update = await page.handle_event(handler, event_data)
    _assert_single_tiny_row500(update, site)
    assert page.items.value[500]["done"] is True
    # Contrast: the full initial render is orders of magnitude larger —
    # the bound is only meaningful because the update is NOT the page.
    assert len(html) > 100 * PAYLOAD_BOUND


@pytest.mark.asyncio
async def test_keyless_toggle_exceeds_bound(tmp_path):
    """RED proof: the same page WITHOUT key= dirties the whole-loop region,
    so the <= 1024 B bound fails — the acceptance above is pinned by the
    keyed-region feature, not incidental."""
    page = _make_page(tmp_path, _src(keyed=False))
    await page._render_template()
    update = await page.handle_event(
        "_handler_0", {"type": "click", "tagName": "BUTTON", "args": {"arg0": 500}}
    )
    total = sum(len(r["html"]) for r in update.get("regions", [])) or len(
        update.get("html", "")
    )
    assert total > PAYLOAD_BOUND


def test_single_toggle_payload_stateless_post(tmp_path):
    """Transport parity: the same toggle through /_pywire/stateless ships
    <= 1 KB of regions."""
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.wire").write_text(_src(keyed=True))
    app = PyWire(pages_dir=str(pages), stateless=True, secret_key="test-secret-key")
    with TestClient(app) as client:
        get = client.get("/")
        assert get.status_code == 200
        blob = get.text.split('_pywire_snapshot" type="text/plain">')[1].split(
            "</script>"
        )[0]
        site = re.search(r'data-pw-region="([^"]+)#500"', get.text).group(1)
        handler, event_data = _row500_dispatch(get.text)
        r = client.post(
            "/_pywire/stateless",
            content=msgpack.packb(
                {
                    "path": "/",
                    "handler": handler,
                    "data": event_data,
                    "snapshot": blob,
                }
            ),
            headers={"Content-Type": "application/x-msgpack"},
        )
        assert r.status_code == 200
        msg = msgpack.unpackb(r.content, raw=False)
        regions = msg["regions"]
        assert [reg["region"] for reg in regions] == [f"{site}#500"]
        total = sum(len(reg["html"]) for reg in regions)
        assert total <= PAYLOAD_BOUND, (
            f"stateless regions payload {total} B exceeds {PAYLOAD_BOUND} B"
        )
