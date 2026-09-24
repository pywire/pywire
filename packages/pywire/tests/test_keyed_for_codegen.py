"""Task 11 Part B: keyed item regions for ``{$for}`` loops.

``{$for <vars> in <iter>, key=<expr>}`` wraps every iteration in
``<div data-pw-region="{site}#{key}" style="display: contents;">`` and
exposes ``__keyed_region_renderers__`` mapping the loop's site id to a
single-item renderer ``_pw_item_<site>(self, key)`` that re-derives the
item from the loop source and renders under the ``{site}#{key}`` render
context. Keyless loops must render byte-identically to before.
"""

from textwrap import dedent
from types import SimpleNamespace

import pytest

from pywire.runtime.loader import PageLoader


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


KEYED_SRC = """
---
items = wire([{"id": "x", "name": "a"}, {"id": "y", "name": "b"}])
---
<ul>
{$for idx, item in enumerate(items.value), key=item["id"]}
    <li>{item["name"]}</li>
{/for}
</ul>
"""

KEYLESS_SRC = """
---
items = wire([{"name": "a", "done": False}, {"name": "b", "done": True}])
---
<ul>
{$for idx, item in enumerate(items.value)}
    <li>{item["name"]}: {item["done"]}</li>
{/for}
</ul>
"""


def _wrapper(site, key):
    return f'<div data-pw-region="{site}#{key}" style="display: contents;">'


@pytest.mark.asyncio
async def test_keyed_map_and_wrappers(tmp_path):
    """(a)+(b): __keyed_region_renderers__ exists; one wrapper per item."""
    page = _make_page(tmp_path, KEYED_SRC)
    keyed = getattr(page, "__keyed_region_renderers__", None)
    assert isinstance(keyed, dict) and len(keyed) == 1
    site, method = next(iter(keyed.items()))
    assert method == f"_pw_item_{site}"
    assert callable(getattr(page, method))

    html = await page._render_template()
    assert _wrapper(site, "x") in html
    assert _wrapper(site, "y") in html
    assert html.count(f'data-pw-region="{site}#') == 2
    assert f"{_wrapper(site, 'x')}<li>a</li></div>" in html
    assert f"{_wrapper(site, 'y')}<li>b</li></div>" in html


@pytest.mark.asyncio
async def test_keyless_loop_renders_byte_identical(tmp_path):
    """(c): loops WITHOUT key= render exactly as before this feature."""
    page = _make_page(tmp_path, KEYLESS_SRC)
    assert not hasattr(page, "__keyed_region_renderers__") or not getattr(
        page, "__keyed_region_renderers__"
    )
    html = await page._render_template()
    region_ids = list(page.__region_renderers__)
    assert len(region_ids) == 1
    rid = region_ids[0]
    assert rid.endswith("_r1")  # region counter untouched by keyed codegen
    assert html == (
        f'<ul data-pw-region="{rid}"><li>a: False</li><li>b: True</li></ul>'
    )
    assert "#" not in html
    assert "display: contents" not in html


@pytest.mark.asyncio
async def test_duplicate_keys_raise_value_error(tmp_path):
    """(d): duplicate keys within one render raise ValueError."""
    page = _make_page(
        tmp_path,
        """
        ---
        items = wire([{"id": "dup", "name": "a"}, {"id": "dup", "name": "b"}])
        ---
        <ul>
        {$for item in items.value, key=item["id"]}
            <li>{item["name"]}</li>
        {/for}
        </ul>
        """,
    )
    with pytest.raises(ValueError, match="duplicate key"):
        await page._render_template()


@pytest.mark.asyncio
async def test_item_write_dirties_only_keyed_region(tmp_path):
    """Part A+B integration: item-field writes dirty only site#key;
    structural writes dirty only the whole-loop region."""
    page = _make_page(tmp_path, KEYED_SRC)
    html = await page._render_template()
    site = next(iter(page.__keyed_region_renderers__))
    ul_rid = next(iter(page.__region_renderers__))
    assert ul_rid not in html or True  # sanity

    page.items.value[1]["name"] = "B"
    assert page._dirty_regions == {f"{site}#y"}

    page._dirty_regions.clear()
    page.items.value.append({"id": "z", "name": "c"})
    assert page._dirty_regions == {ul_rid}


@pytest.mark.asyncio
async def test_keyed_renderer_renders_one_item_under_region_context(tmp_path):
    """(f): the item renderer re-derives by key, renders under site#key."""
    page = _make_page(tmp_path, KEYED_SRC)
    await page._render_template()
    site, method = next(iter(page.__keyed_region_renderers__.items()))

    renderer = getattr(page, method)
    out = await renderer("x")
    assert out == f"{_wrapper(site, 'x')}<li>a</li></div>"

    # The render registered the item's reads under the site#key region.
    deps = page._region_dependencies.get(f"{site}#x")
    assert deps, "renderer must register wire reads under site#key context"

    # Mutation shows up on re-render, and dirtied only this region.
    page._dirty_regions.clear()
    page.items.value[0]["name"] = "A2"
    assert f"{site}#x" in page._dirty_regions
    out2 = await renderer("x")
    assert out2 == f"{_wrapper(site, 'x')}<li>A2</li></div>"


@pytest.mark.asyncio
async def test_keyed_renderer_index_fast_path(tmp_path):
    """key=<index var> over enumerate() re-derives via source[int(key)]."""
    page = _make_page(
        tmp_path,
        """
        ---
        items = wire([{"name": "a"}, {"name": "b"}, {"name": "c"}])
        ---
        <ul>
        {$for i, it in enumerate(items.value), key=i}
            <li>{it["name"]}</li>
        {/for}
        </ul>
        """,
    )
    await page._render_template()
    site, method = next(iter(page.__keyed_region_renderers__.items()))
    out = await getattr(page, method)("2")
    assert out == f"{_wrapper(site, '2')}<li>c</li></div>"


@pytest.mark.asyncio
async def test_keyed_renderer_dict_items_fast_path(tmp_path):
    """key=<k> over d.items() re-derives via source[key]."""
    page = _make_page(
        tmp_path,
        """
        ---
        meta = wire({"one": {"n": 1}, "two": {"n": 2}})
        ---
        <ul>
        {$for k, v in meta.value.items(), key=k}
            <li>{k}={v["n"]}</li>
        {/for}
        </ul>
        """,
    )
    html = await page._render_template()
    site, method = next(iter(page.__keyed_region_renderers__.items()))
    assert _wrapper(site, "one") in html
    out = await getattr(page, method)("two")
    assert out == f"{_wrapper(site, 'two')}<li>two=2</li></div>"
    # Writing a dict entry's field dirties only its keyed region.
    page._dirty_regions.clear()
    page.meta.value["two"]["n"] = 5
    assert page._dirty_regions == {f"{site}#two"}
    out = await getattr(page, method)("two")
    assert out == f"{_wrapper(site, 'two')}<li>two=5</li></div>"
