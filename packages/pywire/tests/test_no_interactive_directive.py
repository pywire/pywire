"""Tests for ``!no_interactive`` directive (#128).

Verifies:
- The directive parses and lifts ``__no_interactive__ = True`` onto the
  compiled page class.
- Pages without the directive default to ``__no_interactive__ = False``.
- The injected ``_pywire_spa_meta`` JSON carries ``page_interactive``
  reflecting the page-level setting.
"""

from __future__ import annotations

import ast as py_ast
import json
import re
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


def test_no_interactive_directive_sets_class_attr():
    src = """!no_interactive
---
---
<p>static</p>
"""
    cls = _compile_source(src, "ni_set")
    assert getattr(cls, "__no_interactive__", None) is True


def test_default_no_interactive_is_false():
    src = """---
---
<p>regular</p>
"""
    cls = _compile_source(src, "ni_default")
    assert getattr(cls, "__no_interactive__", None) is False


@pytest.mark.asyncio
async def test_meta_carries_page_interactive_false_when_directive_set():
    src = """!no_interactive
---
---
<html><head></head><body><p>x</p></body></html>
"""
    cls = _compile_source(src, "ni_meta_false")
    page = cls(_make_request(), {}, {})
    response = await page.render()
    html = response.body.decode("utf-8")
    m = re.search(r'<script id="_pywire_spa_meta"[^>]*>([^<]+)</script>', html)
    assert m, "Expected _pywire_spa_meta script in rendered HTML"
    meta = json.loads(m.group(1))
    assert meta.get("page_interactive") is False


@pytest.mark.asyncio
async def test_meta_carries_page_interactive_true_by_default():
    src = """---
---
<html><head></head><body><p>x</p></body></html>
"""
    cls = _compile_source(src, "ni_meta_true")
    page = cls(_make_request(), {}, {})
    response = await page.render()
    html = response.body.decode("utf-8")
    m = re.search(r'<script id="_pywire_spa_meta"[^>]*>([^<]+)</script>', html)
    assert m, "Expected _pywire_spa_meta script in rendered HTML"
    meta = json.loads(m.group(1))
    assert meta.get("page_interactive") is True
