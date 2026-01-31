from typing import Any

import pytest
from pywire.compiler.exceptions import PyWireSyntaxError
from pywire.compiler.parser import PyWireParser


def parse(html: str) -> Any:
    parser = PyWireParser()
    return parser.parse(html)


def test_event_syntax_enforcement() -> None:
    """Test that @event attributes must use brackets."""
    # Valid
    parse("<button @click={handler}></button>")

    # Invalid (quoted)
    # Invalid (quoted)
    with pytest.raises(PyWireSyntaxError, match="must be wrapped in brackets"):
        parse('<button @click="handler"></button>')


def test_conditional_syntax_enforcement() -> None:
    """Test that $if/$show attributes must use brackets."""
    # Valid
    parse("<div $if={cond}></div>")
    parse("<div $show={cond}></div>")

    # Invalid
    with pytest.raises(PyWireSyntaxError, match="must be wrapped in brackets"):
        parse('<div $if="cond"></div>')
    with pytest.raises(PyWireSyntaxError, match="must be wrapped in brackets"):
        parse('<div $show="cond"></div>')


def test_loop_syntax_enforcement() -> None:
    """Test that $for/$key attributes must use brackets."""
    # Valid
    parse("<div $for={item in items}></div>")
    parse("<div $key={item.id}></div>")

    # Invalid
    with pytest.raises(PyWireSyntaxError, match="must be wrapped in brackets"):
        parse('<div $for="item in items"></div>')
    with pytest.raises(PyWireSyntaxError, match="must be wrapped in brackets"):
        parse('<div $key="item.id"></div>')


def test_reactive_syntax_removal() -> None:
    """Test that :prop syntax is no longer supported as special attribute."""
    # :prop should be treated as literal string attribute
    parsed = parse('<div :title="val"></div>')
    div = parsed.template[0]
    assert ":title" in div.attributes
    assert div.attributes[":title"] == "val"
    # Should NOT be special attribute
    # Note: ReactiveAttribute usually strips ':' from name.
    # If it was parsed as special, we'd see a ReactiveAttribute with name='title'
    # Check special attributes
    has_reactive = False
    for attr in div.special_attributes:
        if attr.__class__.__name__ == "ReactiveAttribute":
            if attr.name == "title":
                has_reactive = True
    assert not has_reactive
