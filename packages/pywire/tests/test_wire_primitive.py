import ast
import pytest
from textwrap import dedent
from pywire.compiler.parser import PyWireParser
from pywire.compiler.codegen.generator import CodeGenerator

def test_wire_primitive_compilation():
    source = dedent("""
    <div>
        Count: {$count}
        <button @click={$count += 1}>Inc</button>
    </div>
    ---
    count = wire(0)
    ---
    """)
    
    parser = PyWireParser()
    parsed = parser.parse(source, "test.pywire")
    
    generator = CodeGenerator()
    module_ast = generator.generate(parsed)
    code = ast.unparse(module_ast)
    
    print("\nGenerated Code:\n", code)
    
    # 1. Verify initialization
    # It might be in __init__ or __top_level_init__
    assert "self.count = wire(0)" in code
    
    # 2. Verify Render Usage
    # {$count} -> self.count.value
    # Note: Interpolation might happen in _render_template
    assert "self.count.value" in code
    
    # 3. Verify Handler Usage
    # @click={$count += 1} -> self.count.value += 1
    # This checks that preprocessor + argument lifter work together
    assert "self.count.value += 1" in code

    # 4. Verify __top_level_init__ calls
    # Should be called in __init__, not just INIT_HOOKS
    assert "self.__top_level_init__()" in code

def test_wire_string_handling():
    """Ensure $ inside strings is NOT replaced."""
    source = dedent("""
    <div>
        Text: {$text}
    </div>
    ---
    text = wire("$100")
    dummy = "$not_a_var"
    ---
    """)
    
    parser = PyWireParser()
    parsed = parser.parse(source, "test.pywire")
    
    generator = CodeGenerator()
    module_ast = generator.generate(parsed)
    code = ast.unparse(module_ast)
    
    print("\nGenerated Code String:\n", code)
    
    # Initialization should keep "$100" literal
    assert 'self.text = wire("$100")' in code or "self.text = wire('$100')" in code
    
    # Dummy assignment should keep "$not_a_var" - literals stay class attributes
    assert "dummy = '$not_a_var'" in code or 'dummy = "$not_a_var"' in code
    
    # Interpolation should work
    assert "self.text.value" in code
