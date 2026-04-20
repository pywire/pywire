"""End-to-end tests for snippet / render / head codegen.

Compiles a minimal .wire source through the full codegen pipeline,
instantiates the resulting page class, renders it, and asserts on the
output HTML.
"""

from __future__ import annotations

import ast as py_ast
from typing import Any, Type

import pytest
from starlette.requests import Request

from pywire_parser.parser import PyWireParser
from pywire.compiler.codegen.generator import CodeGenerator
from pywire.runtime.page import BasePage


def _compile_source(
    source: str, module_name: str = "test_snippet_module"
) -> Type[BasePage]:
    parsed = PyWireParser().parse(source, f"/virtual/{module_name}.wire")
    gen = CodeGenerator()
    module_ast = gen.generate(parsed)
    py_ast.fix_missing_locations(module_ast)
    code = compile(module_ast, filename=f"<{module_name}>", mode="exec")
    ns: dict[str, Any] = {"__name__": module_name}
    exec(code, ns)
    # Class name is `CamelCase(stem) + "Page"` — use the last class whose
    # name ends with "Page" (handles cross-test module-reload quirks where
    # isinstance/issubclass checks against imported BasePage can be stale).
    for name in reversed(list(ns.keys())):
        v = ns[name]
        if isinstance(v, type) and name.endswith("Page") and name != "BasePage":
            return v
    raise RuntimeError("No Page class was generated")


def _make_request(scope_path: str = "/") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": scope_path,
        "raw_path": scope_path.encode(),
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
async def test_snippet_basic_same_scope():
    """Snippet defined and invoked in the same file."""
    src = """---
---
{$snippet greet(name)}
<p>Hello, {name}!</p>
{/snippet}
<div>
{$render greet("world")}
</div>
"""
    cls = _compile_source(src, "basic_same_scope")
    page = cls(_make_request(), {}, {})
    html = await page._render_template()
    assert "<p>Hello, world!</p>" in html


@pytest.mark.asyncio
async def test_render_fallback_when_snippet_missing():
    """Fallback body renders when the snippet prop is None."""
    src = """---
from pywire.core.props import props
from pywire.core.snippet import Snippet

@props
class Props:
    row: Snippet | None = None
---
<ul>
{$render row("x")}<li>fallback</li>{/render}
</ul>
"""
    cls = _compile_source(src, "render_fallback")
    page = cls(_make_request(), {}, {})
    # row is None (default) → fallback runs
    html = await page._render_template()
    assert "<li>fallback</li>" in html


@pytest.mark.asyncio
async def test_head_contribution():
    src = """---
---
{$head}
<title>My Page</title>
<meta name="desc" content="x">
{/head}
<p>body</p>
"""
    cls = _compile_source(src, "head_basic")
    page = cls(_make_request(), {}, {})
    html = await page._render_template()
    assert "<p>body</p>" in html
    # Head content went into buffer, not into main HTML
    assert "<title>My Page</title>" not in html
    flushed = page._flush_head()
    assert "<title>My Page</title>" in flushed
    assert '<meta name="desc" content="x">' in flushed


@pytest.mark.asyncio
async def test_snippet_with_for_loop():
    src = """---
---
{$snippet row(item)}
<li>{item}</li>
{/snippet}
<ul>
{$for item in items}
{$render row(item)}
{/for}
</ul>
"""
    cls = _compile_source(src, "snippet_for")
    page = cls(_make_request(), {}, {})
    page.items = ["a", "b", "c"]  # type: ignore[attr-defined]
    html = await page._render_template()
    assert "<li>a</li>" in html
    assert "<li>b</li>" in html
    assert "<li>c</li>" in html


@pytest.mark.asyncio
async def test_snippet_required_prop_must_be_provided():
    """A required ``Snippet`` prop with no default must be passed at
    init. Props machinery, not render, enforces this."""
    src = """---
from pywire.core.props import props
from pywire.core.snippet import Snippet

@props
class Props:
    row: Snippet
---
{$render row("x")}
"""
    cls = _compile_source(src, "snippet_required")
    with pytest.raises(TypeError, match="row"):
        cls(_make_request(), {}, {})


@pytest.mark.asyncio
async def test_snippet_passed_to_child_component_via_nested_sugar(
    tmp_path, monkeypatch
):
    """Nested ``{$snippet}`` in a component tag is passed as a prop.

    Compiles two files — a ``List`` component declaring a ``row``
    ``Snippet`` prop, and a page that uses ``<List><{$snippet row(item)}>`` sugar.
    Verifies the snippet renders inside the child.
    """
    # Put both compiled files under a synthetic package so imports work.
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")

    list_src = """---
from pywire.core.props import props
from pywire.core.snippet import Snippet

@props
class Props:
    items: list
    row: Snippet
---
<ul>
{$for item in items}
{$render row(item)}
{/for}
</ul>
"""
    page_src = """---
from pkg.list_comp import List
---
<List items={items}>
  {$snippet row(item)}<li>{item}</li>{/snippet}
</List>
"""
    # Compile the List component into a python module file
    import sys

    parsed_list = PyWireParser().parse(list_src, "/virtual/pkg/list.wire")
    list_mod_ast = CodeGenerator().generate(parsed_list)
    py_ast.fix_missing_locations(list_mod_ast)
    list_code = compile(list_mod_ast, filename="<list_comp>", mode="exec")
    list_ns: dict[str, Any] = {"__name__": "pkg.list_comp"}
    exec(list_code, list_ns)
    # Expose generated ListPage under the ``List`` name the page imports.
    list_ns["List"] = list_ns["ListPage"]
    import types as _types

    list_module = _types.ModuleType("pkg.list_comp")
    list_module.__dict__.update(list_ns)
    monkeypatch.setitem(sys.modules, "pkg.list_comp", list_module)

    # Also register a minimal "pkg" namespace in sys.modules
    pkg_mod = _types.ModuleType("pkg")
    monkeypatch.setitem(sys.modules, "pkg", pkg_mod)

    parsed_page = PyWireParser().parse(page_src, "/virtual/page.wire")
    page_mod_ast = CodeGenerator().generate(parsed_page)
    py_ast.fix_missing_locations(page_mod_ast)
    page_code = compile(page_mod_ast, filename="<page>", mode="exec")
    page_ns: dict[str, Any] = {"__name__": "page"}
    exec(page_code, page_ns)
    PageCls = page_ns.get("PagePage")
    assert PageCls is not None

    page = PageCls(_make_request(), {}, {})
    page.items = ["a", "b", "c"]  # type: ignore[attr-defined]
    html = await page._render_template()
    assert "<li>a</li>" in html
    assert "<li>b</li>" in html
    assert "<li>c</li>" in html


@pytest.mark.asyncio
async def test_optional_snippet_none_raises_without_fallback():
    """Unpaired ``{$render name(args)}`` on a None snippet raises,
    signaling that a fallback should have been provided."""
    src = """---
from pywire.core.props import props
from pywire.core.snippet import Snippet

@props
class Props:
    row: Snippet | None = None
---
{$render row("x")}
"""
    cls = _compile_source(src, "snippet_no_fallback")
    page = cls(_make_request(), {}, {})
    with pytest.raises(TypeError, match="required snippet 'row'"):
        await page._render_template()


def test_duplicate_snippet_name_rejected():
    """Two ``{$snippet X}`` definitions at the same scope fail to parse."""
    from pywire_parser.exceptions import PyWireSyntaxError

    src = """---
---
{$snippet dup}<em>first</em>{/snippet}
{$snippet dup}<strong>second</strong>{/snippet}
{$render dup}
"""
    with pytest.raises(PyWireSyntaxError, match="Duplicate .*dup"):
        PyWireParser().parse(src)


def test_snippet_name_collides_with_frontmatter_var():
    """``{$snippet X}`` where ``X`` is a frontmatter symbol is a compile
    error — otherwise the frontmatter value would silently shadow the
    snippet."""
    from pywire_parser.exceptions import PyWireSyntaxError

    src = """---
header = "from-python"
---
{$snippet header}<strong>hi</strong>{/snippet}
{$render header}
"""
    with pytest.raises(PyWireSyntaxError, match="collides with the frontmatter"):
        _compile_source(src, "snippet_collision")


@pytest.mark.asyncio
async def test_children_prop_defaults_to_none_without_explicit_default():
    """``children: Snippet`` (no default) must not make the page's
    kwarg required — the caller's body supplies it implicitly."""
    src = """---
from pywire.core.props import props
from pywire.core.snippet import Snippet

@props
class Props:
    children: Snippet
---
<div class="wrap">{$render children}fallback{/render}</div>
"""
    cls = _compile_source(src, "children_no_default")
    # Instantiating without children kwarg must not raise.
    page = cls(_make_request(), {}, {})
    html = await page._render_template()
    assert "fallback" in html


@pytest.mark.asyncio
async def test_missing_snippet_error_names_snippet_and_class():
    """Required-snippet error now includes the snippet name, class
    name, and author-visible source location."""
    src = """---
from pywire.core.props import props
from pywire.core.snippet import Snippet

@props
class Props:
    children: Snippet
---
{$render children}
"""
    cls = _compile_source(src, "missing_snippet_err")
    page = cls(_make_request(), {}, {})
    with pytest.raises(TypeError) as excinfo:
        await page._render_template()
    msg = str(excinfo.value)
    assert "MissingSnippetErrPage" in msg
    assert "'children'" in msg


@pytest.mark.asyncio
async def test_render_arg_mismatch_rewrites_mangled_name():
    """A wrong-arg-count ``{$render pair(1)}`` raises a TypeError
    whose message references the author-visible name ``pair`` rather
    than the codegen's internal ``_snippet_pair_<line>_<col>_<n>``."""
    src = """---
---
{$snippet pair(a, b)}<span>{a}-{b}</span>{/snippet}
{$render pair(1)}
"""
    cls = _compile_source(src, "arg_mismatch")
    page = cls(_make_request(), {}, {})
    with pytest.raises(TypeError) as excinfo:
        await page._render_template()
    msg = str(excinfo.value)
    assert "{$render pair}" in msg
    assert "_snippet_pair_" not in msg
