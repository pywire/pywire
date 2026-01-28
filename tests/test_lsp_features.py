from pywire_lsp.server import PyWireDocument  # type: ignore


def test_extract_routes_dict() -> None:
    text = """!path { 'main': '/main', 'detail': '/detail/:id' }
---
def setup():
    pass
"""
    doc = PyWireDocument("file:///test.pywire", text)
    routes = doc.routes
    assert len(routes) == 2
    assert routes["main"] == "/main"
    assert routes["detail"] == "/detail/:id"


def test_extract_routes_string() -> None:
    text = """!path '/simple'
---
"""
    doc = PyWireDocument("file:///test.pywire", text)
    routes = doc.routes
    assert len(routes) == 1
    assert routes["main"] == "/simple"


def test_extract_routes_empty() -> None:
    text = """
<div />
"""
    doc = PyWireDocument("file:///test.pywire", text)
    assert len(doc.routes) == 0


def test_extract_routes_multiline() -> None:
    """Test that multi-line !path dictionaries are parsed correctly."""
    text = """!path {
    'main': '/',
    'test': '/a/:id'
}
---
def setup():
    pass
"""
    doc = PyWireDocument("file:///test.pywire", text)
    routes = doc.routes
    assert len(routes) == 2, f"Expected 2 routes, got {len(routes)}: {routes}"
    assert routes["main"] == "/"
    assert routes["test"] == "/a/:id"


def test_directive_ranges_multiline() -> None:
    """Test that directive_ranges tracks multi-line !path correctly."""
    text = """!path {
    'main': '/',
    'test': '/a/:id'
}
---
"""
    doc = PyWireDocument("file:///test.pywire", text)
    assert "path" in doc.directive_ranges
    start, end = doc.directive_ranges["path"]
    assert start == 0
    assert end == 3  # Line with closing brace


def test_interpolation_range() -> None:
    """Test that get_interpolation_at only returns valid if cursor is inside the braces."""
    text = "{name}"
    doc = PyWireDocument("file:///test.pywire", text)

    # Cursor at '{' (index 0)
    interp = doc.get_interpolation_at(0, 0)
    assert interp is None, "Should not match at opening brace"

    # Cursor at 'n' (index 1)
    interp = doc.get_interpolation_at(0, 1)
    assert interp is not None
    assert interp["name"] == "name"
    assert interp["char_in_value"] == 0

    # Cursor at 'e' (index 4)
    interp = doc.get_interpolation_at(0, 4)
    assert interp is not None
    assert interp["char_in_value"] == 3

    # Cursor after 'e' (index 5, before '}')
    interp = doc.get_interpolation_at(0, 5)
    assert interp is not None
    assert interp["char_in_value"] == 4

    # Cursor at '}' (index 5 is '}', oh wait len('{name}') is 6. indices 0..5
    # '{' at 0. 'n' at 1. 'a' at 2. 'm' at 3. 'e' at 4. '}' at 5.
    # value_start = 1. value_end = 5.

    # If cursor at 5 ('}'), char == value_end. Should match.
    interp = doc.get_interpolation_at(0, 5)
    assert interp is not None

    # Cursor after '}' (index 6)
    interp = doc.get_interpolation_at(0, 6)
    assert interp is None, "Should not match after closing brace"


def test_nested_interpolation() -> None:
    """Test that get_interpolation_at handles nested braces in f-strings."""
    # This mimics: <p>{f"Any: {params['id']}" if path["any"] else "None"}</p>
    text = '<p>{f"Any: {x}" if path["any"] else "None"}</p>'
    doc = PyWireDocument("file:///test.pywire", text)

    # The interpolation should be the entire expression: f"Any: {x}" if path["any"] else "None"
    # Full line: <p>{f"Any: {x}" if path["any"] else "None"}</p>
    #            0123456789...
    # '{' at 3, '}' at 44

    # Find position of 'path' - it's after 'if ' in the expression
    # Line: <p>{f"Any: {x}" if path["any"] else "None"}</p>
    path_pos = text.find("path")

    interp = doc.get_interpolation_at(0, path_pos)
    assert interp is not None, f"Should find interpolation at pos {path_pos}"
    assert "path" in interp["value"], (
        f"Interpolation value should contain 'path': {interp['value']}"
    )


if __name__ == "__main__":
    try:
        test_extract_routes_dict()
        test_extract_routes_string()
        test_extract_routes_empty()
        test_extract_routes_multiline()
        test_directive_ranges_multiline()
        test_interpolation_range()
        test_nested_interpolation()
        print("LSP tests passed!")
    except AssertionError as e:
        print(f"LSP test failed: {e}")
        raise
