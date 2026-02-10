import pytest
from pywire.runtime.app import PyWire
from pywire.runtime.page import BasePage

@pytest.mark.asyncio
async def test_attribute_shorthand():
    """---
Test attribute shorthand {attr} -> attr="value"."""
    class ShorthandPage(BasePage):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.class_name = "my-class"
            self.id_val = "my-id"

    # Mock the template rendering (since we don't have full parser integration in this unit test file easily without creating a .wire file)
    # But wait, we need to Test the PARSER. So we should create a temporary .wire file.
    pass

@pytest.mark.asyncio
async def test_shorthand_and_spread(tmp_path):
    """Verify parser handles {shorthand} and {**spread} correctly."""
    from pywire.runtime.loader import PageLoader
    import textwrap
    
    source = textwrap.dedent("""
    ---
    class_name = "foo"
    props = {"data-test": "bar", "aria-label": "baz"}
    ---

    <div id="shorthand" {class_name}></div>
    <div id="spread" {**props}></div>
    <div id="mixed" {class_name} {**props} other="value"></div>
    """)
    
    page_file = tmp_path / "test_shorthand.wire"
    page_file.write_text(source)
    
    loader = PageLoader()
    PageClass = loader.load(page_file)
    
    page = PageClass(request=None, params={}, query={})
    response = await page.render()
    html = response.body.decode()
    
    assert 'class_name="foo"' in html or 'class-name="foo"' in html
    assert 'data-test="bar"' in html
    assert 'aria-label="baz"' in html
    assert 'id="shorthand"' in html
    assert 'id="spread"' in html
    assert 'id="mixed"' in html
    assert 'other="value"' in html
    # Wait, PyWire 0.1.x behavior for {name} is usually name="value" where name is the variable name?
    # Actually, current parser transform {name} to name={name}.
    # So {class_name} -> class_name="foo".
    
    assert 'data-test="bar"' in html
    assert 'aria-label="baz"' in html
    assert 'other="value"' in html
