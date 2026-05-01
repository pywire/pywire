"""Tests for class/style dict & list attribute binding (#152)."""

from __future__ import annotations

import ast as py_ast
from typing import Any, Type

import pytest
from starlette.requests import Request

from pywire_parser.parser import PyWireParser
from pywire.compiler.codegen.generator import CodeGenerator
from pywire.runtime.attrs import normalize_attr
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


def test_normalize_class_list():
    assert normalize_attr("class", ["a", "b", "c"]) == "a b c"


def test_normalize_class_tuple_skips_falsy():
    assert normalize_attr("class", ("a", "", "b", None, "c")) == "a b c"


def test_normalize_class_dict_truthy_keys():
    assert normalize_attr("class", {"a": True, "b": False, "c": 1, "d": 0}) == "a c"


def test_normalize_class_str_passthrough():
    assert normalize_attr("class", "btn primary") == "btn primary"


def test_normalize_style_dict():
    assert normalize_attr("style", {"color": "red", "font-size": "12px"}) == (
        "color:red;font-size:12px"
    )


def test_normalize_style_dict_skips_none_false():
    assert (
        normalize_attr("style", {"color": "red", "display": None, "border": False})
        == "color:red"
    )


def test_normalize_style_str_passthrough():
    assert normalize_attr("style", "color: red") == "color: red"


def test_normalize_other_attr_str():
    assert normalize_attr("id", 42) == "42"
    assert normalize_attr("data-x", "value") == "value"


@pytest.mark.asyncio
async def test_codegen_class_list_binding():
    """`<div class={['a', 'b']}>` renders with class='a b'."""
    src = """---
classes = ["a", "b"]
---
<div class={classes}></div>
"""
    cls = _compile_source(src, "class_list")
    page = cls(_make_request(), {}, {})
    html = await page._render_template()
    assert 'class="a b"' in html


@pytest.mark.asyncio
async def test_codegen_class_dict_binding():
    """`<div class={{'a': True, 'b': False}}>` renders with class='a'."""
    src = """---
state = {"a": True, "b": False, "c": 1}
---
<div class={state}></div>
"""
    cls = _compile_source(src, "class_dict")
    page = cls(_make_request(), {}, {})
    html = await page._render_template()
    assert 'class="a c"' in html


@pytest.mark.asyncio
async def test_codegen_style_dict_binding():
    """`<div style={{'color': 'red'}}>` renders style as `;`-joined pairs."""
    src = """---
sty = {"color": "red", "font-size": "12px"}
---
<div style={sty}></div>
"""
    cls = _compile_source(src, "style_dict")
    page = cls(_make_request(), {}, {})
    html = await page._render_template()
    assert "color:red" in html
    assert "font-size:12px" in html
