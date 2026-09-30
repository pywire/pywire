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


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "  JavaScript:alert(1)",
        "java\tscript:alert(1)",
        "\x01javascript:alert(1)",
        "vbscript:msgbox(1)",
        "data:text/html,<script>alert(1)</script>",
    ],
)
def test_script_urls_blocked_in_href(value):
    assert normalize_attr("href", value) == "about:invalid#blocked"
    assert normalize_attr("formaction", value) == "about:invalid#blocked"


def test_ordinary_urls_pass():
    for value in ("/a?x=javascript:1", "https://example.com", "mailto:a@b.c", "#top"):
        assert normalize_attr("href", value) == value
    # An image may be a data: URL; script schemes still aren't.
    assert normalize_attr("src", "data:image/png;base64,AAAA").startswith("data:")
    assert normalize_attr("src", "javascript:alert(1)") == "about:invalid#blocked"


@pytest.mark.parametrize(
    "style",
    [
        {"background": "url(//attacker.example/x)"},
        {"width": "expression(alert(1))"},
        {"color": "red;background:url(//attacker.example)"},
        {"color": "red}</style><script>"},
        {"color;x": "red"},
        {"color": "\\75rl(//attacker.example)"},
    ],
)
def test_unsafe_style_declarations_dropped(style):
    assert normalize_attr("style", {"margin": "0", **style}) == "margin:0"


def test_css_custom_properties_allowed():
    assert normalize_attr("style", {"--gap": "4px"}) == "--gap:4px"


def test_spread_attribute_names_are_checked():
    from pywire.runtime.helpers import render_attrs

    html = render_attrs(
        {"class": "a"},
        {
            'x onmouseover="alert(1)"': "y",
            "onmouseover": "alert(1)",
            "OnClick": "alert(1)",
            "><script>": "1",
            "data-id": "7",
            "aria-label": "ok",
            "@click": "open = true",
            "href": "javascript:alert(1)",
        },
    )
    assert "onmouseover" not in html and "OnClick" not in html
    assert "<script" not in html
    assert 'data-id="7"' in html and 'aria-label="ok"' in html
    assert '@click="open = true"' in html
    assert 'href="about:invalid#blocked"' in html


@pytest.mark.asyncio
async def test_codegen_href_binding_blocks_script_url():
    src = """---
link = "javascript:alert(document.cookie)"
---
<a href={link}>x</a>
"""
    cls = _compile_source(src, "href_binding")
    page = cls(_make_request(), {}, {})
    html = await page._render_template()
    assert 'href="about:invalid#blocked"' in html
