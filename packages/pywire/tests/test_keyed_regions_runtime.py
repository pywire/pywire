"""Task 12: keyed region dispatch in ``render_update``.

Dirty ``{site}#{key}`` region ids dispatch through
``__keyed_region_renderers__`` and emit ONE wrapper-inclusive region
patch per item. Missing site, missing key (item deleted since dirtying)
or renderer exceptions fall back to the existing full-render path —
never a crash, never a stuck UI.
"""

from textwrap import dedent
from types import SimpleNamespace

import pytest

from pywire.runtime.loader import PageLoader

ROWS_SRC = """
---
items = wire([{"id": str(i), "name": "item-%d" % i, "done": False} for i in range(100)])
---
<ul>
{$for item in items.value, key=item["id"]}
    <li>{item['name']}:{item['done']}</li>
{/for}
</ul>
"""


def _make_page(tmp_path, source, name="page.wire"):
    file_path = tmp_path / name
    file_path.write_text(dedent(source).strip() + "\n")
    cls = PageLoader().load(file_path, use_cache=False)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(sibling_paths=[], enable_pjax=False, debug=False)
        )
    )
    return cls(request, {}, {}, {}, None)


def _wrapper(site, key):
    return f'<div data-pw-region="{site}#{key}" style="display: contents;">'


async def _bootstrapped(tmp_path):
    """Page with initial render done (subscriptions registered)."""
    page = _make_page(tmp_path, ROWS_SRC)
    await page._render_template()
    site = next(iter(page.__keyed_region_renderers__))
    ul_rid = next(iter(page.__region_renderers__))
    return page, site, ul_rid


@pytest.mark.asyncio
async def test_item_write_patches_only_that_row(tmp_path):
    """(a) items.value[50]['done'] = True → ONE region ending #50,
    single-row HTML purity, output cache keyed by the full site#key id."""
    page, site, _ = await _bootstrapped(tmp_path)

    page.items.value[50]["done"] = True
    assert page._dirty_regions == {f"{site}#50"}

    update = await page.render_update()
    assert update["type"] == "regions"
    regions = update["regions"]
    assert len(regions) == 1
    r = regions[0]
    assert r["region"] == f"{site}#50"
    html = r["html"]
    # Wrapper-inclusive payload (client patches [data-pw-region] div→div).
    assert html.startswith(_wrapper(site, "50"))
    assert html.endswith("</div>")
    assert "item-50" in html
    assert "item-49" not in html
    assert "item-51" not in html
    assert html.count("<li>") == 1
    # Output-equality cache keyed by the full site#key id.
    assert page._region_output_cache[f"{site}#50"] == html


@pytest.mark.asyncio
async def test_append_patches_whole_loop_region(tmp_path):
    """(b) structural write → whole-loop region (base site id, no #)
    with all 101 item wrappers."""
    page, site, ul_rid = await _bootstrapped(tmp_path)

    page.items.value.append({"id": "100", "name": "item-100", "done": False})
    assert page._dirty_regions == {ul_rid}

    update = await page.render_update()
    assert update["type"] == "regions"
    regions = update["regions"]
    assert len(regions) == 1
    r = regions[0]
    assert r["region"] == ul_rid
    assert "#" not in r["region"]
    assert "item-100" in r["html"]
    assert r["html"].count(f'data-pw-region="{site}#') == 101


@pytest.mark.asyncio
async def test_deleted_dirty_row_falls_back_to_full_render(tmp_path):
    """(c) race: item deleted after its region dirtied → full-render
    fallback, no exception, no stuck UI."""
    page, site, _ = await _bootstrapped(tmp_path)

    page.items.value[50]["done"] = True
    assert f"{site}#50" in page._dirty_regions
    page.items.value.pop(50)  # also dirties the whole-loop region

    update = await page.render_update()
    assert update["type"] == "full"
    assert "item-50" not in update["html"]
    assert "item-49" in update["html"]


@pytest.mark.asyncio
async def test_two_item_writes_two_single_row_regions(tmp_path):
    """(d) sequential writes to different rows → two regions, each
    carrying exactly one row."""
    page, site, _ = await _bootstrapped(tmp_path)

    page.items.value[10]["done"] = True
    page.items.value[20]["done"] = True
    assert page._dirty_regions == {f"{site}#10", f"{site}#20"}

    update = await page.render_update()
    assert update["type"] == "regions"
    by_id = {r["region"]: r["html"] for r in update["regions"]}
    assert set(by_id) == {f"{site}#10", f"{site}#20"}
    for key, other in (("10", "20"), ("20", "10")):
        html = by_id[f"{site}#{key}"]
        assert f"item-{key}" in html
        assert f"item-{other}" not in html
        assert html.count("<li>") == 1
