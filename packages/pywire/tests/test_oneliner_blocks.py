"""Regression tests for oneliner brace-block syntax (#155).

Single-line paired blocks like ``{$if cond}A{/if}`` compile cleanly
through the existing block codegen — no special pathway needed.
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
async def test_oneliner_if_truthy():
    src = """---
cond = True
---
<p>{$if cond}A{/if}</p>
"""
    cls = _compile_source(src, "ol_if_t")
    page = cls(_make_request(), {}, {})
    html = await page._render_template()
    assert ">A</p>" in html


@pytest.mark.asyncio
async def test_oneliner_if_falsy():
    src = """---
cond = False
---
<p>{$if cond}A{/if}</p>
"""
    cls = _compile_source(src, "ol_if_f")
    page = cls(_make_request(), {}, {})
    html = await page._render_template()
    assert "A" not in html


@pytest.mark.asyncio
async def test_oneliner_if_else():
    src = """---
cond = False
---
<p>{$if cond}A{$else}B{/if}</p>
"""
    cls = _compile_source(src, "ol_if_else")
    page = cls(_make_request(), {}, {})
    html = await page._render_template()
    assert ">B</p>" in html
    assert "A" not in html


@pytest.mark.asyncio
async def test_oneliner_for():
    src = """---
items = [1, 2, 3]
---
<ul>{$for it in items}<li>{it}</li>{/for}</ul>
"""
    cls = _compile_source(src, "ol_for")
    page = cls(_make_request(), {}, {})
    html = await page._render_template()
    assert "<li>1</li>" in html
    assert "<li>2</li>" in html
    assert "<li>3</li>" in html


@pytest.mark.asyncio
async def test_chained_oneliner_ifs():
    src = """---
cond = True
---
<span>{$if cond}X{/if}{$if not cond}Y{/if}</span>
"""
    cls = _compile_source(src, "ol_chained")
    page = cls(_make_request(), {}, {})
    html = await page._render_template()
    assert ">X" in html
    # Whitespace from the {/if} → {$if not cond} gap may slip through;
    # the assertion is that "Y" is excluded, not strict whitespace.
    assert "Y" not in html
