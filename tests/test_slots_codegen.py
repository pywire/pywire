import unittest
from pywire.compiler.parser import PyWireParser
from pywire.compiler.codegen.template import TemplateCodegen
from pywire.compiler.ast_nodes import TemplateNode

class MockCompiler:
    def __init__(self):
        self.scope_id = "test_scope"

import ast
from typing import Union, List, Any, cast

class TestSlotCodegen(unittest.TestCase):
    def normalize_ast(self, node: Union[ast.AST, List[ast.AST]]) -> Union[ast.AST, List[ast.AST]]:
        if isinstance(node, list):
            for n in node:
                self.normalize_ast(n)
            return node

        for child in ast.walk(node):
            if not hasattr(child, "lineno"):
                c = cast(Any, child)
                c.lineno = 1
                c.end_lineno = 1
                c.col_offset = 0
                c.end_col_offset = 0
        return node

    def test_named_slot_registration(self):
        source = """
---html---
<MyComponent>
    <template slot="header">Header Content</template>
    <template slot="footer">Footer Content</template>
</MyComponent>
"""
        parser = PyWireParser()
        ast = parser.parse(source)
        codegen = TemplateCodegen()
        
        # We need to simulate the environment where MyComponent is a known component
        # TemplateCodegen.generate_render_method generates the _render_template function
        
        # Helper to simulate component map
        # lxml lowercases tags, so key must be lowercase
        comp_map = {"mycomponent": "MyComponent"}
        
        func_def, _ = codegen.generate_render_method(ast.template, component_map=comp_map)
        
        # Convert AST to string
        import ast as python_ast
        self.normalize_ast(func_def)
        
        code = python_ast.unparse(func_def)
        
        # Check for slot registration dict passed to component
        # slots={'header': ..., 'footer': ...}
        self.assertIn("'header'", code)
        self.assertIn("'footer'", code)
        self.assertIn("slots={", code)

    def test_explicit_slot_definition(self):
        source = """
---html---
<div>
    <slot name="my-slot">Default Content</slot>
</div>
"""
        parser = PyWireParser()
        ast = parser.parse(source)
        codegen = TemplateCodegen()
        func_def, _ = codegen.generate_render_method(ast.template)
        import ast as python_ast
        self.normalize_ast(func_def)
        code = python_ast.unparse(func_def)
        
        # Logic: render_slot("my-slot", ...)
        self.assertIn('render_slot', code)
        self.assertIn("'my-slot'", code)

    def test_default_slot_definition(self):
        source = """
---html---
<div>
    <slot>Default</slot>
</div>
"""
        parser = PyWireParser()
        ast = parser.parse(source)
        codegen = TemplateCodegen()
        func_def, _ = codegen.generate_render_method(ast.template)
        import ast as python_ast
        self.normalize_ast(func_def)
        code = python_ast.unparse(func_def)
        
        self.assertIn('render_slot', code)
        self.assertIn("'default'", code)

if __name__ == "__main__":
    unittest.main()
