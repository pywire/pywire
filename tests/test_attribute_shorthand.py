import pytest
from pywire.compiler.parser import PyWireParser
from pywire.compiler.ast_nodes import ReactiveAttribute

def test_attr_shorthand():
    parser = PyWireParser()
    # Note: we need at least one separator to make it valid page
    source = """
---html---
<div {disabled}></div>
<input {checked} {validation_error}>
"""
    ast = parser.parse(source)
    nodes = ast.template
    
    # 1. First div
    div = nodes[0]
    assert div.tag == "div"
    # special attributes filter
    attrs = [a for a in div.special_attributes if isinstance(a, ReactiveAttribute)]
    assert len(attrs) == 1
    
    attr = attrs[0]
    assert attr.name == "disabled"
    assert attr.expr == "disabled"
    
    # 2. Input
    inp = nodes[1] # Note: might be text node (newline) in between?
    # parser usually keeps text nodes.
    # checking children/structure
    
    # scan for input
    inp = next(n for n in nodes if n.tag == "input")
    
    attrs = [a for a in inp.special_attributes if isinstance(a, ReactiveAttribute)]
    assert len(attrs) == 2
    
    names = {a.name for a in attrs}
    assert "checked" in names
    assert "validation_error" in names
