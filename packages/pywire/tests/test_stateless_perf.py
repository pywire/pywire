"""CI perf smoke: loose bounds that catch 10x regressions, not noise.

Measured on a dev box (scratch/adhoc/bench_stateless.py): counter stateless
round-trip p50 ~0.06 ms server-side (~3 ms incl. TestClient), counter
snapshot 232 B, 1000-row single-toggle regions ~251 B. Bounds sit 10-50x
above measurement so slow CI hosts never flake — they only trip on
algorithmic regressions (e.g. shipping the whole loop instead of one row).
"""

import json
import re
import statistics
import time
from pathlib import Path
from types import SimpleNamespace

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire
from pywire.runtime.loader import PageLoader

FIXTURE_PAGES = Path(__file__).parent / "fixtures" / "stateless_app" / "pages"
SECRET = "test-secret-key"

COUNTER_ROUND_TRIP_MS = 50.0
COUNTER_SNAPSHOT_B = 500
TOGGLE_PAYLOAD_B = 2048

# Same 1000-row keyed fixture as tests/test_keyed_region_payload.py
# (comprehension var `k` — `i` would shadow toggle's arg).
_PAGE_SRC = """---
items = wire([{"name": "item-" + str(k), "done": False} for k in range(1000)])

def toggle(i):
    items.value[i]["done"] = not items.value[i]["done"]
---
<ul id="rows">
{$for idx, item in enumerate(items.value), key=idx}
    <li><span>{item["name"]}</span><span>{item["done"]}</span><button @click={toggle(idx)}>toggle</button></li>
{/for}
</ul>
"""


@pytest.fixture()
def client():
    app = PyWire(pages_dir=str(FIXTURE_PAGES), stateless=True, secret_key=SECRET)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _blob(html: str) -> str:
    return html.split('_pywire_snapshot" type="text/plain">')[1].split("</script>")[0]


def _post(client, blob: str) -> "object":
    return client.post(
        "/_pywire/stateless",
        content=msgpack.packb(
            {"path": "/", "handler": "increment", "data": {}, "snapshot": blob}
        ),
        headers={"Content-Type": "application/x-msgpack"},
    )


def test_counter_event_round_trip_under_50ms(client):
    """Median full stateless round-trip (decode+verify+resolve+instantiate+
    restore+event+render+re-snapshot+encode) stays far under 50 ms."""
    blob = _blob(client.get("/").text)
    for _ in range(3):  # warmup: page compile + caches
        assert _post(client, blob).status_code == 200
    samples = []
    for _ in range(10):
        t0 = time.perf_counter()
        r = _post(client, blob)
        samples.append((time.perf_counter() - t0) * 1e3)
    assert r.status_code == 200
    med = statistics.median(samples)
    assert med < COUNTER_ROUND_TRIP_MS, f"counter round-trip {med:.1f} ms"


def test_counter_snapshot_under_500_bytes(client):
    blob = _blob(client.get("/").text)
    assert len(blob) < COUNTER_SNAPSHOT_B, f"snapshot {len(blob)} B"


@pytest.mark.asyncio
async def test_1000_row_toggle_payload_under_2kb(tmp_path):
    """Real client event shape (`_handler_N` + args): toggling ONE row of a
    1000-row keyed list ships one tiny region, not the whole loop."""
    file_path = tmp_path / "page.wire"
    file_path.write_text(_PAGE_SRC)
    cls = PageLoader().load(file_path, use_cache=False)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(sibling_paths=[], enable_pjax=False, debug=False)
        )
    )
    page = cls(request, {}, {}, {}, None)
    html = await page._render_template()

    m = re.search(
        r'data-pw-region="[^"]+#500"[^>]*>.*?data-on-click="([^"]+)"[^>]*'
        r'data-arg-0="([^"]+)"',
        html,
        re.S,
    )
    assert m, "row-500 keyed wrapper with toggle button not found"
    handler, arg = m.group(1), json.loads(m.group(2))
    assert arg == 500

    update = await page.handle_event(
        handler, {"type": "click", "tagName": "BUTTON", "args": {"arg0": arg}}
    )
    assert update["type"] == "regions"
    total = sum(len(r["html"]) for r in update["regions"])
    assert total < TOGGLE_PAYLOAD_B, f"toggle payload {total} B"
