import textwrap
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
    source = textwrap.dedent("""
        ---
        x = 1
        def foo():
            pass
        ---
        <h1>Hi</h1>
    """).strip()
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
    source = textwrap.dedent("""
        <div class={
            'active' if True
            else 'inactive'
        }></div>
    """).strip()
    transpiler = Transpiler(source)
    code, _ = transpiler.transpile()
    
    assert "'active' if True" in code
    assert "else 'inactive'" in code

def test_transpile_wrappers():
    source = textwrap.dedent("""
        <div $if={x > 1}></div>
        <div $for={i in items}></div>
        <div @click={do_something()}></div>
    """).strip()
    transpiler = Transpiler(source)
    code, _ = transpiler.transpile()
    
    # Check for wrappers
    assert "if (x > 1):" in code or "if x > 1:" in code
    assert "for i in items:" in code
    assert "def __handler" in code
    assert "do_something()" in code

def test_explicit_property_mapping():
    """Test that {count.value} maps 'count' correctly."""
    source = textwrap.dedent("""
        ---
        count = wire(0)
        ---
        <p>{count.value}</p>
    """).strip()
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
    """Test @click={count.value += 1} mapping."""
    source = textwrap.dedent("""
        ---
        count = wire(0)
        ---
        <button @click={count.value += 1}>Inc</button>
    """).strip()
    transpiler = Transpiler(source)
    code, source_map = transpiler.transpile()
    
    # Usage: {count.value}
    # <button @click={count...
    # c is at 16.
    usage_line = 3
    usage_col_start = 16
    
    gen_loc = source_map.to_generated(usage_line, usage_col_start)
    assert gen_loc is not None
    
    gen_line, gen_col = gen_loc
    gen_lines = code.splitlines()
    target_line = gen_lines[gen_line]
    
    extracted = target_line[gen_col:gen_col+5]
    assert extracted == "count"

def test_transpile_v017_brace_syntax():
    source = """
    {$if count > 0}
        <p>{count}</p>
    {$elif count < 0}
        <p>Neg</p>
    {$else}
        <p>Zero</p>
    {/if}
    {$for item in items}
        <p>{item}</p>
    {/for}
    """
    transpiler = Transpiler(source)
    code, _ = transpiler.transpile()
    
    # Check for keywords and expressions
    # Note: elif currently maps to "if (" in my implementation for simplicitly of expression checking
    assert "if (count > 0): pass" in code
    assert "if (count < 0): pass" in code
    assert "else: pass" in code
    assert "for item in items: pass" in code

def test_sourcemap_control_flow():
    """Test sourcemaps for {$ blocks."""
    cases = [
        ("{$if loading}", "loading"),
        ("{$  if loading}", "loading"),
        ("{$for x in items}", "x in items"),
        ("{$html page.title}", "page.title"),
    ]

    for source_line, expected_expr in cases:
        t = Transpiler(source_line)
        gen, sm = t.transpile()
        
        # Verify mapping for expected_expr start
        # expected_expr start in source
        orig_col = source_line.find(expected_expr)
        
        # find where expected_expr is in generated code
        gen_idx = gen.find(expected_expr)
        assert gen_idx != -1, f"Expression {expected_expr} not found in {gen}"
        
        # Calculate gen line/col
        gen_lines = gen.splitlines(keepends=True)
        current_idx = 0
        g_line = 0
        g_col = 0
        for line in gen_lines:
            if current_idx + len(line) > gen_idx:
                g_col = gen_idx - current_idx
                break
            current_idx += len(line)
            g_line += 1
            
        # Check mapping
        found = False
        for m in sm.mappings:
            if m.generated_line == g_line and m.generated_col == g_col:
                assert m.original_col == orig_col, f"Mapping mismatch for {expected_expr}: expected {orig_col}, got {m.original_col}"
                found = True
                break
        
        assert found, f"No mapping found for {expected_expr} at {g_line}:{g_col}"

def test_multiline_attribute_mapping():
    """Test that attributes spanning multiple lines map correctly (Prettier format)."""
    source = """<input
  type="number"
  value={current_age.value}
  @input={update_current_age}
/>"""
    t = Transpiler(source)
    code, sm = t.transpile()
    
    # Check value={current_age.value} (line 2, col 9)
    # Note: current_age starts at col 9
    m_val = sm.to_generated(2, 9)
    assert m_val is not None, "Should map current_age on line 2"
    
    # Check @input={update_current_age} (line 3, col 10)
    # Note: update_current_age starts at col 10
    m_input = sm.to_generated(3, 10)
    assert m_input is not None, "Should map update_current_age on line 3"
    
    # Reverse mapping check
    # Find update_current_age in code
    idx = code.find("update_current_age")
    gen_lines = code.splitlines(keepends=True)
    curr = 0
    g_line, g_col = 0, 0
    for line in gen_lines:
        if curr + len(line) > idx:
            g_col = idx - curr
            break
        curr += len(line)
        g_line += 1
    
    orig = sm.to_original(g_line, g_col)
    assert orig is not None
    assert orig[0] == 3 # line 3
    assert orig[1] == 10 # col 10
