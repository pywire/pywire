import pytest
from pywire_language_server.transpiler import Transpiler

def test_transpile_simple_interpolation():
    source = """<div>{name}</div>"""
    transpiler = Transpiler(source)
    code, sourcemap = transpiler.transpile()
    
    # We expect 'name' to be in the generated python.
    assert "name" in code
    # We expect a mapping for 'name'.
    # This assertion is vague, we'll refine it as we implement.

def test_transpile_python_section():
    source = """
x = 1
def foo():
    pass
---html---
<h1>Hi</h1>
"""
    transpiler = Transpiler(source)
    code, _ = transpiler.transpile()
    
    assert "x = 1" in code
    assert "def foo():" in code
    assert "<h1>" not in code # HTML should be stripped/commented

def test_transpile_directive():
    source = """!path '/home'"""
    transpiler = Transpiler(source)
    code, _ = transpiler.transpile()
    
    # Directives should be preserved in some python-valid form
    assert "'/home'" in code

def test_transpile_multiline_interpolation():
    source = """<div class={
    'active' if True
    else 'inactive'
}></div>"""
    transpiler = Transpiler(source)
    code, _ = transpiler.transpile()
    
    assert "'active' if True" in code
    assert "else 'inactive'" in code

def test_transpile_wrappers():
    source = """
    <div $if={x > 1}></div>
    <div $for={i in items}></div>
    <div @click={do_something()}></div>
    """
    transpiler = Transpiler(source)
    code, _ = transpiler.transpile()
    
    # Check for wrappers
    assert "if (x > 1):" in code or "if x > 1:" in code
    assert "for i in items:" in code
    assert "def __handler" in code
    assert "do_something()" in code

def test_variable_rewrite_mapping():
    """Test that $count maps to count in generated code."""
    source = """
count = wire(0)
---html---
<p>{$count}</p>
"""
    transpiler = Transpiler(source)
    code, source_map = transpiler.transpile()
    
    # usage: {$count} -> $ is at col 4. count is at col 5.
    usage_line = 3 
    usage_col_start = 5 
    
    gen_loc = source_map.to_generated(usage_line, usage_col_start)
    assert gen_loc is not None
    
    gen_line, gen_col = gen_loc
    gen_lines = code.splitlines()
    target_line = gen_lines[gen_line]
    
    # extracted length 5 for 'count'
    extracted = target_line[gen_col:gen_col+5]
    assert extracted == "count"

def test_explicit_property_mapping():
    """Test that {count.value} maps 'count' correctly."""
    source = """
count = wire(0)
---html---
<p>{count.value}</p>
"""
    transpiler = Transpiler(source)
    code, source_map = transpiler.transpile()
    
    usage_line = 3
    usage_col_start = 4 # { is at 3, count at 4
    
    gen_loc = source_map.to_generated(usage_line, usage_col_start)
    assert gen_loc is not None
    
    gen_line, gen_col = gen_loc
    gen_lines = code.splitlines()
    target_line = gen_lines[gen_line]
    
    extracted = target_line[gen_col:gen_col+5]
    assert extracted == "count"

def test_event_handler_mapping():
    """Test @click={$count} mapping."""
    source = """
count = wire(0)
---html---
<button @click={$count += 1}>Inc</button>
"""
    transpiler = Transpiler(source)
    code, source_map = transpiler.transpile()
    
    # Usage: {$count}
    # <button @click={$count...
    # $ is at 16. count at 17.
    usage_line = 3
    usage_col_start = 17
    
    gen_loc = source_map.to_generated(usage_line, usage_col_start)
    assert gen_loc is not None
    
    gen_line, gen_col = gen_loc
    gen_lines = code.splitlines()
    target_line = gen_lines[gen_line]
    
    extracted = target_line[gen_col:gen_col+5]
    assert extracted == "count"
