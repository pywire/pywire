import pytest
from pywire.core import ref, Ref
from pywire.runtime.page import BasePage
from pywire.compiler.codegen.template import TemplateCodegen
from pywire.compiler.parser import PyWireParser
from unittest.mock import MagicMock
import ast

@pytest.fixture
def mock_page():
    mock_request = MagicMock()
    # BasePage(request, params, query)
    return BasePage(mock_request, {}, {})

def test_ref_factory():
    """Test the ref() factory function."""
    r = ref()
    assert isinstance(r, Ref)
    assert r._bound_type is None
    
    # Test type hint support (no runtime effect)
    class MyComp: pass
    r2 = ref[MyComp]()
    assert isinstance(r2, Ref)

def test_ref_binding(mock_page):
    """Test that refs bind correctly to elements and pages."""
    r = ref()
    
    r._bind("element", "test-ref-id", mock_page)
    assert r._bound_type == "element"
    assert r._ref_id == "test-ref-id"
    assert mock_page._refs_by_id["test-ref-id"] == r

def test_ref_data_sync(mock_page):
    """Test that ref data and value synchronize correctly."""
    r = ref()
    r._bind("form", "form-1", mock_page)
    
    # Mock client event data
    r._update_data({"name": "John", "age": 30})
    assert r.data == {"name": "John", "age": 30}
    
    r2 = ref()
    r2._bind("input", "input-1", mock_page)
    r2._update_value("hello")
    assert r2.value == "hello"

def test_ref_commands(mock_page):
    """Test command queueing and collection."""
    r = ref()
    r._bind("element", "el-1", mock_page)
    
    r.focus()
    r.scroll_to(behavior="smooth")
    
    commands = r._collect_commands()
    assert len(commands) == 2
    assert commands[0]["cmd"] == "focus"
    assert commands[1]["cmd"] == "scrollTo"
    assert commands[1]["args"] == {"behavior": "smooth"}
    
    # Should be empty after collection
    assert len(r._collect_commands()) == 0

def test_ref_extended_dom(mock_page):
    """Test extended DOM methods (classes, attributes)."""
    r = ref()
    r._bind("element", "el-1", mock_page)
    
    r.add_class("active")
    r.remove_class("old")
    r.toggle_class("visible")
    r.set_attribute("data-test", "val")
    r.remove_attribute("disabled")
    
    commands = r._collect_commands()
    assert len(commands) == 5
    assert commands[0] == {"cmd": "addClass", "refId": "el-1", "args": {"name": "active"}}
    assert commands[1] == {"cmd": "removeClass", "refId": "el-1", "args": {"name": "old"}}
    assert commands[2] == {"cmd": "toggleClass", "refId": "el-1", "args": {"name": "visible"}}
    assert commands[3] == {"cmd": "setAttribute", "refId": "el-1", "args": {"name": "data-test", "value": "val"}}
    assert commands[4] == {"cmd": "removeAttribute", "refId": "el-1", "args": {"name": "disabled"}}

def test_ref_request_rect(mock_page):
    """Test the request_rect command and its synchronization."""
    r = ref()
    r._bind("element", "el-1", mock_page)
    
    r.request_rect()
    commands = r._collect_commands()
    assert commands[0] == {"cmd": "requestRect", "refId": "el-1", "args": {}}
    
    # Simulate client sending back rect in next event
    mock_rect = {"x": 10, "y": 20, "width": 100, "height": 50}
    r._update_rect(mock_rect)
    assert r.rect == mock_rect

def test_codegen_ref_binding():
    """Test that codegen generates the correct binding code for elements."""
    codegen = TemplateCodegen()
    parser = PyWireParser()
    
    template = '<div $ref={my_ref}></div>'
    parsed = parser.parse(template)
    
    # Create a mock body to collect AST
    body = []
    local_vars = {"my_ref"}
    
    # We simulate the _add_node call
    codegen._add_node(parsed.template[0], body, local_vars, None, "L1", set(), set(), set(), set(), {}, "S1")
    
    # Fix missing locations before unparse
    for stmt in body:
        ast.fix_missing_locations(stmt)
        
    code = ast.unparse(body)
    assert "my_ref._bind('element', self._handler_prefix + 'pw-ref-1-0', self)" in code
    assert "attrs['data-pw-ref'] = str(unwrap_wire(self._handler_prefix + 'pw-ref-1-0'))" in code
    assert "'$ref'" not in code

def test_codegen_form_ref_binding():
    """Test that codegen identifies forms correctly for refs."""
    codegen = TemplateCodegen()
    parser = PyWireParser()
    
    template = '<form $ref={f}></form>'
    parsed = parser.parse(template)
    
    body = []
    codegen._add_node(parsed.template[0], body, {"f"}, None, "L1", set(), set(), set(), set(), {}, "S1")
    
    for stmt in body:
        ast.fix_missing_locations(stmt)
        
    code = ast.unparse(body)
    assert "f._bind('form', self._handler_prefix + 'pw-ref-1-0', self)" in code

def test_component_ref_binding():
    """Test that codegen handles component refs correctly."""
    codegen = TemplateCodegen()
    parser = PyWireParser()
    
    # Mock a component
    template = '<MyComp $ref={comp_ref} />'
    parsed = parser.parse(template)
    
    body = []
    codegen._add_node(parsed.template[0], body, {"comp_ref"}, None, "L1", set(), set(), set(), set(), {"MyComp": "MyCompClass"}, "S1")
    
    for stmt in body:
        ast.fix_missing_locations(stmt)
        
    code = ast.unparse(body)
    # The variable name is _comp_line_column
    assert "_comp_1_0 =" in code
    assert "comp_ref._bind_component(_comp_1_0, self)" in code
