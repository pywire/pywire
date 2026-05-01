"""End-to-end tests for ``{$dynamic}`` memoization escape.

Verifies that:

- Snippet invocations are memoized across renders by default
  (``BasePage._invoke_snippet_inner`` caches by site_id + arg equality).
- A ``{$dynamic} ... {/dynamic}`` wrapper bypasses that cache for any
  snippet/render-region invocation in its subtree, even with identical
  args.
- The bypass is scoped: regions outside the wrapper continue to memoize.
- Nested ``{$dynamic}`` blocks behave (idempotent — depth-counted).
"""

from __future__ import annotations

import ast as py_ast
from typing import Any, Type

import pytest
from starlette.requests import Request

from pywire_parser.parser import PyWireParser
from pywire.compiler.codegen.generator import CodeGenerator
from pywire.runtime.page import BasePage


def _compile_source(source: str, module_name: str) -> Type[BasePage]:
    parsed = PyWireParser().parse(source, f"/virtual/{module_name}.wire")
    gen = CodeGenerator()
    module_ast = gen.generate(parsed)
    py_ast.fix_missing_locations(module_ast)
    code = compile(module_ast, filename=f"<{module_name}>", mode="exec")
    ns: dict[str, Any] = {"__name__": module_name}
    exec(code, ns)
    for name in reversed(list(ns.keys())):
        v = ns[name]
        if isinstance(v, type) and name.endswith("Page") and name != "BasePage":
            return v
    raise RuntimeError("No Page class was generated")


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 0),
        "server": ("testserver", 80),
        "scheme": "http",
        "root_path": "",
        "http_version": "1.1",
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_snippet_memoization_baseline_caches_identical_args():
    """Same site_id + same args → second render hits cache."""
    src = """---
---
{$snippet row(x)}
<li>{x}</li>
{/snippet}
<ul>
{$render row(1)}
</ul>
"""
    cls = _compile_source(src, "memo_baseline")
    page = cls(_make_request(), {}, {})

    h1 = await page._render_template()
    assert "<li>1</li>" in h1

    # The site_id assigned at the {$render} call should be in the
    # invocation cache after first render.
    assert len(page._snippet_invocations) == 1
    site_id, (cached_args, cached_html) = next(iter(page._snippet_invocations.items()))
    assert "<li>1</li>" in cached_html


@pytest.mark.asyncio
async def test_dynamic_block_skips_snippet_cache():
    """A {$dynamic} wrapper around a {$render} bypasses the per-site cache."""
    src = """---
---
{$snippet row(x)}
<li>{x}</li>
{/snippet}
{$dynamic}
<ul>
{$render row(1)}
</ul>
{/dynamic}
"""
    cls = _compile_source(src, "dynamic_skip")
    page = cls(_make_request(), {}, {})

    await page._render_template()
    # Inside {$dynamic} the cache is dropped after each invocation, so
    # the per-site cache should be empty.
    assert page._snippet_invocations == {}


@pytest.mark.asyncio
async def test_dynamic_does_not_leak_to_sibling_renders():
    """Sibling {$render} calls outside {$dynamic} continue to memoize."""
    src = """---
---
{$snippet row(x)}
<li>{x}</li>
{/snippet}
<section>
{$dynamic}
{$render row(1)}
{/dynamic}
{$render row(2)}
</section>
"""
    cls = _compile_source(src, "dynamic_resets")
    page = cls(_make_request(), {}, {})

    await page._render_template()
    # The dynamic-wrapped invocation is NOT cached. The trailing
    # invocation outside the block IS cached. Net cache size: 1.
    assert len(page._snippet_invocations) == 1


@pytest.mark.asyncio
async def test_dynamic_nested_blocks_render_all_content():
    """Nested {$dynamic} blocks all render their content correctly."""
    src = """---
---
{$dynamic}
<p>outer</p>
{$dynamic}
<p>inner</p>
{/dynamic}
<p>after-inner</p>
{/dynamic}
"""
    cls = _compile_source(src, "dynamic_nested")
    page = cls(_make_request(), {}, {})

    html = await page._render_template()
    assert "<p>outer</p>" in html
    assert "<p>inner</p>" in html
    assert "<p>after-inner</p>" in html


@pytest.mark.asyncio
async def test_dynamic_block_with_no_children_is_noop():
    """Empty {$dynamic} block compiles and doesn't blow up."""
    src = """---
---
<p>before</p>
{$dynamic}
{/dynamic}
<p>after</p>
"""
    cls = _compile_source(src, "dynamic_empty")
    page = cls(_make_request(), {}, {})

    html = await page._render_template()
    assert "<p>before</p>" in html
    assert "<p>after</p>" in html


@pytest.mark.asyncio
async def test_wire_write_seq_increments_on_invalidate():
    """`_invalidate_wire` bumps the global wire-write counter."""
    src = """---
---
<p>x</p>
"""
    cls = _compile_source(src, "wseq_basic")
    page = cls(_make_request(), {}, {})
    assert page._wire_write_seq == 0

    # Simulate a wire write reaching this page.
    page._invalidate_wire(object(), "field")
    assert page._wire_write_seq == 1

    page._invalidate_wire(object(), "field")
    assert page._wire_write_seq == 2


@pytest.mark.asyncio
async def test_invoke_component_caches_when_props_and_wires_unchanged():
    """Component HTML cached when props unchanged + captured wires unchanged."""
    from pywire import wire
    from pywire.core.wire import set_render_context, reset_render_context

    src = """---
---
<p>parent</p>
"""
    cls = _compile_source(src, "comp_memo")
    page = cls(_make_request(), {}, {})

    used_wire = wire(0)

    class _ChildPage(BasePage):
        async def _render_and_cleanup(self) -> str:  # type: ignore[override]
            self._render_calls = getattr(self, "_render_calls", 0) + 1
            # Real components set render context inside their region
            # methods; mimic that so the wire read registers as a dep
            # on the component (which is what _invoke_component captures).
            tok = set_render_context(self, "child_region")
            try:
                _ = used_wire.value
            finally:
                reset_render_context(tok)
            return "<span>child</span>"

    child = _ChildPage(_make_request(), {}, {})
    child.attrs = {"x": 1}

    h1 = await page._invoke_component(child)
    h2 = await page._invoke_component(child)
    assert h1 == h2 == "<span>child</span>"
    assert child._render_calls == 1  # second invocation hit the cache

    # Mutate the captured wire → cache invalidates on next call.
    used_wire.value = 1
    h3 = await page._invoke_component(child)
    assert h3 == "<span>child</span>"
    assert child._render_calls == 2


@pytest.mark.asyncio
async def test_invoke_component_ignores_unread_wire_changes():
    """Bumping a wire the component never read does NOT invalidate its cache."""
    from pywire import wire
    from pywire.core.wire import set_render_context, reset_render_context

    src = """---
---
<p>parent</p>
"""
    cls = _compile_source(src, "comp_unread_wire")
    page = cls(_make_request(), {}, {})

    read_wire = wire(0)
    other_wire = wire(0)

    class _ChildPage(BasePage):
        async def _render_and_cleanup(self) -> str:  # type: ignore[override]
            self._render_calls = getattr(self, "_render_calls", 0) + 1
            tok = set_render_context(self, "child_region")
            try:
                _ = read_wire.value
            finally:
                reset_render_context(tok)
            return "<span>c</span>"

    child = _ChildPage(_make_request(), {}, {})
    child.attrs = {"x": 1}

    await page._invoke_component(child)
    other_wire.value = 99  # bump a wire the child didn't read
    await page._invoke_component(child)
    assert child._render_calls == 1  # cache hit — other_wire is irrelevant

    read_wire.value = 1  # bump the wire the child DID read
    await page._invoke_component(child)
    assert child._render_calls == 2  # cache miss — re-rendered


@pytest.mark.asyncio
async def test_invoke_component_invalidates_on_prop_change():
    src = """---
---
<p>p</p>
"""
    cls = _compile_source(src, "comp_props_change")
    page = cls(_make_request(), {}, {})

    class _ChildPage(BasePage):
        async def _render_and_cleanup(self) -> str:  # type: ignore[override]
            self._render_calls = getattr(self, "_render_calls", 0) + 1
            return f"<span>{self.attrs.get('x')}</span>"

    child = _ChildPage(_make_request(), {}, {})
    child.attrs = {"x": 1}
    await page._invoke_component(child)
    child.attrs = {"x": 2}
    out = await page._invoke_component(child)
    assert out == "<span>2</span>"
    assert child._render_calls == 2


@pytest.mark.asyncio
async def test_codegen_emits_bypass_kwarg_inside_dynamic_block():
    """Generated code includes `_pw_bypass_memo=True` on _invoke_render
    calls within a {$dynamic} block — the decision is baked at codegen
    time so it survives partial render_update cycles."""
    src = """---
---
{$snippet row(x)}
<li>{x}</li>
{/snippet}
<ul>
{$render row(1)}
</ul>
{$dynamic}
<ul>
{$render row(2)}
</ul>
{/dynamic}
"""
    parsed = PyWireParser().parse(src, "/virtual/codegen_check.wire")
    gen = CodeGenerator()
    module_ast = gen.generate(parsed)
    py_ast.fix_missing_locations(module_ast)
    src_out = py_ast.unparse(module_ast)
    # The plain `{$render row(1)}` should NOT carry the bypass kwarg…
    assert "_pw_bypass_memo=True" in src_out
    # …and the bypass should appear at least once (the dynamic-wrapped call).
    occurrences = src_out.count("_pw_bypass_memo=True")
    invocations = src_out.count("self._invoke_render")
    assert invocations >= 2
    assert occurrences == 1, (
        f"expected exactly one bypass occurrence (the dynamic-wrapped render); "
        f"got {occurrences} across {invocations} invocations"
    )


@pytest.mark.asyncio
async def test_codegen_emits_dynamic_regions_class_attr():
    """Regions emitted under `{$dynamic}` get tagged in `__dynamic_regions__`
    so runtime can force-dirty them every update."""
    src = """---
from pywire import wire
x = wire(0)
---
<p>plain {x}</p>
{$dynamic}
<p>dynamic {x}</p>
{/dynamic}
"""
    parsed = PyWireParser().parse(src, "/virtual/dyn_regions.wire")
    gen = CodeGenerator()
    module_ast = gen.generate(parsed)
    py_ast.fix_missing_locations(module_ast)
    src_out = py_ast.unparse(module_ast)
    assert "__dynamic_regions__" in src_out, (
        "codegen should emit __dynamic_regions__ when a {$dynamic} block "
        "wraps a region; got:\n" + src_out
    )


@pytest.mark.asyncio
async def test_dynamic_region_force_dirty_in_render_update():
    """`__dynamic_regions__` are unioned into `_dirty_regions` at the top
    of `render_update` so the bypass kwarg on inner _invoke_render calls
    actually executes every cycle."""
    src = """---
---
<p>plain</p>
"""
    cls = _compile_source(src, "dyn_force_dirty")
    page = cls(_make_request(), {}, {})

    page.__class__.__dynamic_regions__ = frozenset({"r_dummy"})  # type: ignore[attr-defined]
    page.__class__.__region_renderers__ = {"r_dummy": "_render_region_dummy"}  # type: ignore[attr-defined]

    calls = {"n": 0}

    async def _render_region_dummy() -> str:
        calls["n"] += 1
        return "<p>dyn</p>"

    page._render_region_dummy = _render_region_dummy  # type: ignore[attr-defined]

    # First render — region runs.
    await page.render_update(init=False)
    # Second render — no wire bumped, no dirty regions, but dynamic region
    # was force-dirtied → renderer ran again.
    await page.render_update(init=False)
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_component_memo_isolated_per_wire():
    """Two child components reading distinct wires — bumping one wire
    invalidates exactly one cache."""
    from pywire import wire
    from pywire.core.wire import set_render_context, reset_render_context

    src = """---
---
<p>p</p>
"""
    cls = _compile_source(src, "comp_isolated")
    page = cls(_make_request(), {}, {})

    wire_a = wire(0)
    wire_b = wire(0)

    class _CardA(BasePage):
        async def _render_and_cleanup(self) -> str:  # type: ignore[override]
            self._render_calls = getattr(self, "_render_calls", 0) + 1
            tok = set_render_context(self, "r")
            try:
                _ = wire_a.value
            finally:
                reset_render_context(tok)
            return "A"

    class _CardB(BasePage):
        async def _render_and_cleanup(self) -> str:  # type: ignore[override]
            self._render_calls = getattr(self, "_render_calls", 0) + 1
            tok = set_render_context(self, "r")
            try:
                _ = wire_b.value
            finally:
                reset_render_context(tok)
            return "B"

    a = _CardA(_make_request(), {}, {})
    b = _CardB(_make_request(), {}, {})
    a.attrs = {}
    b.attrs = {}

    await page._invoke_component(a)
    await page._invoke_component(b)
    assert a._render_calls == 1
    assert b._render_calls == 1

    wire_a.value = 1  # bump A's wire only
    await page._invoke_component(a)
    await page._invoke_component(b)
    assert a._render_calls == 2  # invalidated
    assert b._render_calls == 1  # unchanged

    wire_b.value = 1  # bump B's wire only
    await page._invoke_component(a)
    await page._invoke_component(b)
    assert a._render_calls == 2  # unchanged
    assert b._render_calls == 2  # invalidated


@pytest.mark.asyncio
async def test_component_memo_invalidates_on_prop_change():
    """Memoization key includes real props captured at
    ``_resolve_component`` time. Real props get setattr'd onto the comp
    instance and don't appear in ``comp.attrs`` — the memo key must
    still detect them."""

    src = """---
---
<p>p</p>
"""
    cls = _compile_source(src, "comp_prop_memo")
    page = cls(_make_request(), {}, {})

    class _Card(BasePage):
        initial: int = 0  # declared prop → setattr path, NOT comp.attrs

        async def _render_and_cleanup(self) -> str:  # type: ignore[override]
            self._render_calls = getattr(self, "_render_calls", 0) + 1
            return f"<div>{self.initial}</div>"

    # Pre-instantiate the component so _resolve_component takes the
    # existing-instance path (avoids needing to thread request/params/query
    # through cls(**kwargs) here).
    comp = _Card(_make_request(), {}, {})
    comp.attrs = {}
    page._components["card"] = comp

    # Simulate codegen: _resolve_component captures memo props, then
    # _invoke_component reads them back.
    page._resolve_component("card", _Card, initial=0)
    await page._invoke_component(comp)
    assert comp._render_calls == 1

    # Same props → cache hit, body does not re-run.
    page._resolve_component("card", _Card, initial=0)
    await page._invoke_component(comp)
    assert comp._render_calls == 1

    # Prop changes → cache miss, body re-runs.
    page._resolve_component("card", _Card, initial=1)
    await page._invoke_component(comp)
    assert comp._render_calls == 2


@pytest.mark.asyncio
async def test_render_update_emits_page_interactive_meta():
    """Every render_update response carries `meta.page_interactive` so
    the client can re-evaluate the !no_interactive flag on SPA nav."""
    src = """---
---
<p>p</p>
"""
    cls = _compile_source(src, "meta_interactive")
    page = cls(_make_request(), {}, {})

    result = await page.render_update(init=False)
    assert "meta" in result
    assert result["meta"].get("page_interactive") is True

    # Flip the class flag — meta should track it.
    page.__class__.__no_interactive__ = True  # type: ignore[attr-defined]
    try:
        result2 = await page.render_update(init=False)
        assert result2["meta"].get("page_interactive") is False
    finally:
        del page.__class__.__no_interactive__


@pytest.mark.asyncio
async def test_dynamic_region_bypasses_static_expr_cache():
    """Impure dep-free expressions (counter()/datetime.now()) inside a
    `{$dynamic}` region must re-execute every render. `_render_expr`
    caches dep-free results in `_static_cache` by default; the dynamic
    region must bypass that cache."""
    src = """---
_count = {"n": 0}

def tick() -> str:
    _count["n"] += 1
    return ""

def n() -> int:
    return _count["n"]
---
{$dynamic}
<p>{tick()}n={n()}</p>
{/dynamic}
"""
    cls = _compile_source(src, "dyn_static_bypass")
    page = cls(_make_request(), {}, {})

    # First full render — tick fires (n=1).
    h1 = await page._render_template()
    assert "n=1" in h1

    # Force-dirty the dynamic region and re-run partial update. tick
    # MUST fire again — counter advances.
    page._expr_counts.clear()
    h2 = await page._render_template()
    assert "n=2" in h2, f"static cache leaked into dynamic region; got {h2!r}"


@pytest.mark.asyncio
async def test_dynamic_block_does_not_create_sub_regions_inside_existing_region():
    """A `{$dynamic}` block inside an already-region-wrapped element must
    not create new sub-regions for its descendants — they should inline
    into the parent region so wire reads register at the parent level."""
    src = """---
from pywire import wire
count = wire(0)
---
<section>
  <h2>plain</h2>
  {$dynamic}
    <ul><li>n={count}</li></ul>
    <p>x={count}</p>
  {/dynamic}
</section>
"""
    parsed = PyWireParser().parse(src, "/virtual/dyn_inline.wire")
    gen = CodeGenerator()
    module_ast = gen.generate(parsed)
    py_ast.fix_missing_locations(module_ast)
    src_out = py_ast.unparse(module_ast)

    # The section becomes a region. There should be exactly ONE region
    # method for that section — descendants inside the dynamic block
    # don't get their own region renderers.
    region_methods = [
        line for line in src_out.splitlines() if "async def _render_region_" in line
    ]
    assert len(region_methods) == 1, (
        f"expected 1 region method for the section; got {len(region_methods)}:\n"
        + "\n".join(region_methods)
    )


@pytest.mark.asyncio
async def test_dynamic_block_tags_enclosing_region_in_dynamic_regions():
    """The region enclosing a `{$dynamic}` block is added to
    `__dynamic_regions__` so it force-dirties on every render — covers
    the wire-free impure case."""
    src = """---
import datetime
---
<section>
  <h2>title</h2>
  {$dynamic}<p>now={datetime.datetime.now()}</p>{/dynamic}
</section>
"""
    parsed = PyWireParser().parse(src, "/virtual/dyn_force_parent.wire")
    gen = CodeGenerator()
    module_ast = gen.generate(parsed)
    py_ast.fix_missing_locations(module_ast)
    src_out = py_ast.unparse(module_ast)

    assert "__dynamic_regions__" in src_out, (
        "expected enclosing region tagged in __dynamic_regions__\n" + src_out
    )


@pytest.mark.asyncio
async def test_dynamic_section_sibling_display_advances_with_wire_bumps():
    """End-to-end: a `<section>` containing a `{$dynamic}` block and a
    sibling impure-display expression. After a wire bump the parent
    region re-renders — both the inside-block rendering AND the sibling
    counter display refresh."""
    src = """---
from pywire import wire

_state = {"runs": 0}

def tick() -> str:
    _state["runs"] += 1
    return ""

def runs() -> int:
    return _state["runs"]

count = wire(0)
---
<section>
  {$dynamic}
    <p>{tick()}count={count}</p>
  {/dynamic}
  <p class="counter">runs={runs()}</p>
</section>
"""
    cls = _compile_source(src, "dyn_sibling_display")
    page = cls(_make_request(), {}, {})

    h1 = await page._render_template()
    assert "count=0" in h1
    assert "runs=1" in h1

    # Bump the wire — parent region must re-render so both `tick()` (inside
    # the dynamic block) AND `runs()` (sibling display) reflect the bump.
    page._expr_counts.clear()
    page.count.value = 1

    update = await page.render_update(init=False)
    if update["type"] == "regions":
        regions = update.get("regions", [])
        combined = "".join(r["html"] for r in regions)
    else:
        combined = update.get("html", "")
    assert "count=1" in combined, f"snippet body did not refresh: {combined!r}"
    assert "runs=2" in combined, (
        f"sibling display did not refresh after wire bump (was the parent "
        f"region not invalidated?): {combined!r}"
    )


@pytest.mark.asyncio
async def test_invoke_component_dynamic_block_bypasses_cache():
    src = """---
---
<p>p</p>
"""
    cls = _compile_source(src, "comp_dynamic_bypass")
    page = cls(_make_request(), {}, {})

    class _ChildPage(BasePage):
        async def _render_and_cleanup(self) -> str:  # type: ignore[override]
            self._render_calls = getattr(self, "_render_calls", 0) + 1
            return "<span>c</span>"

    child = _ChildPage(_make_request(), {}, {})
    child.attrs = {"x": 1}

    # Codegen sets _pw_bypass_memo=True for components inside a {$dynamic} block.
    await page._invoke_component(child, _pw_bypass_memo=True)
    await page._invoke_component(child, _pw_bypass_memo=True)
    assert child._render_calls == 2  # bypass active — every call re-renders
