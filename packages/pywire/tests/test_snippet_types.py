"""Unit tests for the render-region primitives in ``pywire.core.snippet``."""

from __future__ import annotations

import pytest

from pywire.core.snippet import (
    Child,
    Children,
    ChildrenType,
    HeadBuffer,
    RenderUnit,
    Snippet,
    SnippetType,
)


# ---------- RenderUnit ----------


@pytest.mark.asyncio
async def test_render_unit_runs_func():
    async def fn(a: int) -> str:
        return f"<p>{a}</p>"

    unit = RenderUnit("u1", fn, name="greet")
    assert await unit.render(7) == "<p>7</p>"


def test_render_unit_cache_miss_when_empty():
    async def fn() -> str:
        return ""

    unit = RenderUnit("u1", fn)
    assert unit.cached(()) is None


def test_render_unit_cache_hit_on_equal_args():
    async def fn() -> str:
        return ""

    unit = RenderUnit("u1", fn)
    unit.store(("a", 1), "<div>ok</div>")
    assert unit.cached(("a", 1)) == "<div>ok</div>"


def test_render_unit_cache_miss_on_different_args():
    async def fn() -> str:
        return ""

    unit = RenderUnit("u1", fn)
    unit.store(("a", 1), "<div>ok</div>")
    assert unit.cached(("a", 2)) is None


def test_render_unit_cache_uses_deep_equality():
    async def fn() -> str:
        return ""

    unit = RenderUnit("u1", fn)
    # Fresh dicts are equal by ==, different by identity.
    unit.store(({"x": 1},), "<html/>")
    assert unit.cached(({"x": 1},)) == "<html/>"


def test_render_unit_cache_safe_fallback_on_broken_eq():
    class Broken:
        def __eq__(self, other):
            raise RuntimeError("boom")

        def __hash__(self):
            return 0

    async def fn() -> str:
        return ""

    b = Broken()
    unit = RenderUnit("u1", fn)
    unit.store((b,), "<a/>")
    # identity still matches
    assert unit.cached((b,)) == "<a/>"
    # different instance should miss (not crash)
    assert unit.cached((Broken(),)) is None


def test_render_unit_invalidate_clears_cache():
    async def fn() -> str:
        return ""

    unit = RenderUnit("u1", fn)
    unit.store((1,), "<x/>")
    unit.invalidate()
    assert unit.cached((1,)) is None


# ---------- Snippet ----------


@pytest.mark.asyncio
async def test_snippet_renders_via_unit():
    async def fn(name: str) -> str:
        return f"<p>{name}</p>"

    snip = Snippet(RenderUnit("u", fn))
    assert await snip.render("world") == "<p>world</p>"


@pytest.mark.asyncio
async def test_snippet_call_syntax():
    async def fn(a: int) -> str:
        return str(a)

    snip = Snippet(RenderUnit("u", fn))
    # Callable sugar: await snip(1)
    assert await snip(41) == "41"


@pytest.mark.asyncio
async def test_snippet_bound_args_prepend():
    async def fn(a: int, b: int) -> str:
        return f"{a}/{b}"

    snip = Snippet(RenderUnit("u", fn), bound_args=(10,))
    assert await snip.render(3) == "10/3"


def test_snippet_type_subscript():
    t = Snippet[str, int]
    assert isinstance(t, SnippetType)
    assert t.arg_types == (str, int)


def test_snippet_type_single_arg():
    t = Snippet[int]
    assert isinstance(t, SnippetType)
    assert t.arg_types == (int,)


# ---------- Child / Children ----------


def test_child_sentinel_is_passthrough():
    assert Child is not None
    # Child[...] returns Child (unused params, symmetry only).
    assert Child[int] is Child


def test_children_exact_count():
    ct = Children[3]
    assert isinstance(ct, ChildrenType)
    ct.validate_count(3)
    with pytest.raises(ValueError):
        ct.validate_count(2)


def test_children_min_max_via_helper():
    ct = Children.of(min=1, max=5)
    ct.validate_count(1)
    ct.validate_count(5)
    with pytest.raises(ValueError):
        ct.validate_count(0)
    with pytest.raises(ValueError):
        ct.validate_count(6)


def test_children_min_only_via_helper():
    ct = Children.of(min=2)
    ct.validate_count(100)
    with pytest.raises(ValueError):
        ct.validate_count(1)


def test_children_dict_params():
    ct = Children[{"min": 1, "max": 3}]
    assert isinstance(ct, ChildrenType)
    ct.validate_count(2)
    with pytest.raises(ValueError):
        ct.validate_count(4)


def test_children_type_rejects_mixed_n_and_range():
    with pytest.raises(ValueError):
        ChildrenType(min=1, n=2)


# ---------- HeadBuffer ----------


def test_head_buffer_flush_orders_title_first():
    hb = HeadBuffer()
    hb.contribute("<title>Home</title><meta name=a>")
    hb.contribute("<link rel=icon>")
    out = hb.flush()
    # Title appears once, first.
    assert out.startswith("<title>Home</title>")
    assert "<meta name=a>" in out
    assert "<link rel=icon>" in out
    assert out.count("<title>") == 1


def test_head_buffer_last_title_wins():
    hb = HeadBuffer()
    hb.contribute("<title>Layout</title>")
    hb.contribute("<title>Page</title>")
    out = hb.flush()
    assert "<title>Page</title>" in out
    assert "<title>Layout</title>" not in out


def test_head_buffer_preserves_non_title_contributions():
    hb = HeadBuffer()
    hb.contribute("<link rel=preload>")
    hb.contribute("<meta name=x>")
    out = hb.flush()
    assert out == "<link rel=preload><meta name=x>"


def test_head_buffer_bool_empty():
    hb = HeadBuffer()
    assert not hb
    hb.contribute("<meta>")
    assert hb
    hb.clear()
    assert not hb
