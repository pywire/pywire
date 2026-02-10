from pywire_language_server.server import PyWireDocument  # type: ignore


def test_directive_ranges_multiline() -> None:
    """Test that directive_ranges tracks multi-line !path correctly."""
    text = """!path {
    'main': '/',
    'test': '/a/:id'
}
---html---
"""
    doc = PyWireDocument("file:///test.pywire", text)
    assert "path" in doc.directive_ranges
    start, end = doc.directive_ranges["path"]
    assert start == 0
    assert end == 3  # Line with closing brace
    # Directives don't need fences if no python code



def test_source_map_roundtrip() -> None:
    text = """---
value = 1
---
<p>{value}</p>
"""
    doc = PyWireDocument("file:///test.pywire", text)
    # value is at line 1, char 0
    gen_pos = doc.map_to_generated(1, 0)
    assert gen_pos is not None
    orig_pos = doc.map_to_original(*gen_pos)
    assert orig_pos == (1, 0)


if __name__ == "__main__":
    try:
        test_directive_ranges_multiline()
        test_source_map_roundtrip()
        print("LSP tests passed!")
    except AssertionError as e:
        print(f"LSP test failed: {e}")
        raise
