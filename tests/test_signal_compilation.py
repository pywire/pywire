import ast
from textwrap import dedent
from pywire.compiler.parser import PyWireParser
from pywire.compiler.codegen.generator import CodeGenerator

def test_derived_decorator_compilation():
    source = dedent("""
        ---
        count = wire(0)
        
        @derived
        def double_count():
            return count.value * 2
        ---
        <div>{double_count}</div>
    """)
    
    parser = PyWireParser()
    parsed = parser.parse(source, "test.wire")
    
    generator = CodeGenerator()
    module_ast = generator.generate(parsed)
    code = ast.unparse(module_ast)
    
    # Check that it's treated as a wire-like variable for unwrap_wire
    assert "unwrap_wire(self.double_count)" in code
    
    # Check that the assignment happens in __top_level_init__
    assert "self.double_count = derived(self.double_count)" in code
    
    # Check that it's added to __page_class__'s wire_vars (via CodeGenerator call sequence)
    # Actually we can't easily check wire_vars set directly from code, but unwrap_wire presence confirms it.

def test_effect_decorator_compilation():
    source = dedent("""
        ---
        count = wire(0)
        
        @effect
        def log_count():
            print(count.value)
        ---
        <div>Check console</div>
    """)
    
    parser = PyWireParser()
    parsed = parser.parse(source, "test.wire")
    
    generator = CodeGenerator()
    module_ast = generator.generate(parsed)
    code = ast.unparse(module_ast)
    
    # Check that effect assignment happens
    assert "self._effect_log_count = effect(self.log_count)" in code

def test_expose_decorator_compilation():
    source = dedent("""
        ---
        @expose
        def reset():
            pass
            
        def internal():
            pass
        ---
        <div>Component</div>
    """)
    
    parser = PyWireParser()
    parsed = parser.parse(source, "test.wire")
    
    generator = CodeGenerator()
    module_ast = generator.generate(parsed)
    code = ast.unparse(module_ast)
    
    # Check __exposed_methods__ class attribute
    assert "__exposed_methods__ = {'reset'}" in code

def test_component_ref_compilation():
    source = dedent("""
        ---
        modal_ref = wire()
        ---
        <Modal ref={modal_ref} title="Hello" />
    """)
    
    parser = PyWireParser()
    parsed = parser.parse(source, "test.wire")
    
    generator = CodeGenerator()
    module_ast = generator.generate(parsed)
    code = ast.unparse(module_ast)
    
    # Check ref assignment groundwork
    # Should find something like: _comp_..._ref = self.modal_ref
    # In my template.py change:
    # comp_var = f"_comp_{node.line}_{node.column}"
    # body.append(ast.Assign(targets=[Attribute(value=Name(id=comp_var...), attr="_ref"...)], value=ref_expr))
    
    assert "._ref = self.modal_ref" in code
