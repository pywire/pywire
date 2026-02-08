import pytest
from pywire.compiler.parser import PyWireParser

def test_permanent_reload_shorthand():
    parser = PyWireParser()
    source = """
---html---
<div $permanent>Permanent</div>
<a href="/test" $reload>Reload</a>
<div id="mixed" class="foo" $permanent data-other="bar">Mixed</div>
"""
    ast = parser.parse(source)
    nodes = [n for n in ast.template if n.tag is not None]
    
    # 1. Permanent div
    div = nodes[0]
    assert div.tag == "div"
    assert div.attributes["data-pywire-permanent"] == "true"
    
    # 2. Reload link
    a = nodes[1]
    assert a.tag == "a"
    assert a.attributes["data-pywire-reload"] == "true"
    assert a.attributes["href"] == "/test"
    
    # 3. Mixed attributes
    mixed = nodes[2]
    assert mixed.tag == "div"
    assert mixed.attributes["id"] == "mixed"
    assert mixed.attributes["class"] == "foo"
    assert mixed.attributes["data-pywire-permanent"] == "true"
    assert mixed.attributes["data-other"] == "bar"

def test_permanent_no_space():
    parser = PyWireParser()
    # $permanent at end of tag
    source = "---html---\n<div $permanent></div>"
    ast = parser.parse(source)
    div = [n for n in ast.template if n.tag == "div"][0]
    assert div.attributes["data-pywire-permanent"] == "true"
    
    # $permanent followed by />
    source = "---html---\n<div $permanent/>"
    ast = parser.parse(source)
    div = [n for n in ast.template if n.tag == "div"][0]
    assert div.attributes["data-pywire-permanent"] == "true"
