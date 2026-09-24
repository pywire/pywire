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


# ---------------------------------------------------------------------------
# Keyed region id safety: escaping + render-time key validation.
# ---------------------------------------------------------------------------

_ONE_ITEM_SRC = """
---
items = wire([{"id": KEY, "name": "a"}])
---
<ul>
{$for item in items.value, key=item["id"]}
    <li>{item["name"]}</li>
{/for}
</ul>
"""


def _src_with_key(key: str) -> str:
    return _ONE_ITEM_SRC.replace("KEY", repr(key))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_key",
    [
        'x" onmouseover="alert(1)',  # attribute-injection / stored XSS attempt
        'a"b',  # raw quote breaks the client querySelector round-trip
        "a\\b",  # backslash is the CSS escape char in selectors
        "a b",  # whitespace
        "a\tb",  # control character
        "a\nb",
    ],
)
async def test_hostile_keys_are_refused(tmp_path, bad_key):
    """Keys that cannot round-trip through the client's
    querySelector('[data-pw-region="<id>"]') raise ValueError at render."""
    page = _make_page(tmp_path, _src_with_key(bad_key))
    with pytest.raises(ValueError, match="unsafe key"):
        await page._render_template()


@pytest.mark.asyncio
async def test_special_char_key_is_escaped_and_round_trips(tmp_path):
    """A benign-but-special key is HTML-escaped in the attribute, and the
    HTML parse round-trips it back to the raw site#key region id — the same
    id the client selector matches and the server tracks regions under."""
    from html.parser import HTMLParser

    key = "a&b<c>"
    page = _make_page(tmp_path, _src_with_key(key))
    html = await page._render_template()
    site = next(iter(page.__keyed_region_renderers__))
    raw_rid = f"{site}#{key}"

    # Escaped on the wire: no raw &, < or > inside the attribute value.
    assert f'data-pw-region="{site}#a&amp;b&lt;c&gt;"' in html
    assert f'data-pw-region="{raw_rid}"' not in html

    # HTML attribute parsing un-escapes back to the raw region id.
    parsed: list = []

    class _Grab(HTMLParser):
        def handle_starttag(self, tag, attrs):
            parsed.extend(v for k, v in attrs if k == "data-pw-region")

    _Grab().feed(html)
    assert raw_rid in parsed

    # Raw id is safe inside the client's quoted querySelector pattern
    # (validation guarantees no quote/backslash/whitespace-control chars).
    assert not any(c in raw_rid for c in '"\\')
    assert all(not c.isspace() and ord(c) >= 32 for c in raw_rid)

    # Server-side item rendering keys off the RAW id and still escapes.
    renderer = getattr(page, f"_pw_item_{site}")
    out = await renderer(key)
    assert out == (
        f'<div data-pw-region="{site}#a&amp;b&lt;c&gt;" '
        f'style="display: contents;"><li>a</li></div>'
    )
    assert page._region_dependencies.get(raw_rid)
