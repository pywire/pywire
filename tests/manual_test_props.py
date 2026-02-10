import ast
from textwrap import dedent
from pywire.compiler.parser import PyWireParser
from pywire.compiler.codegen.generator import CodeGenerator

def test_props_decorator_compilation():
    source = dedent("""
        ---
        from pywire import props
        
        @props
        class Props:
            name: str
            count: int = 0
            variant: str = "primary"
        ---
        <div>{name} ({count})</div>
    """)
    
    parser = PyWireParser()
    parsed = parser.parse(source, "test.wire")
    
    generator = CodeGenerator()
    module_ast = generator.generate(parsed)
    code = ast.unparse(module_ast)
    
    print("Generated code:")
    print(code)
    
    # Check __init__ signature
    # Should have: __init__(self, request, params, query, path=None, url=None, *, name, count='0', variant="'primary'", **kwargs)
    # Wait, type hints are unparsed too.
    
    assert "def __init__(self, request, params, query, path=None, url=None, *, name: str, count: int=0, variant: str='primary', **kwargs):" in code
    assert "self.name = name" in code
    assert "self.count = count" in code
    assert "self.variant = variant" in code

if __name__ == "__main__":
    test_props_decorator_compilation()
    print("Test passed!")
