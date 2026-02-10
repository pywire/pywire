import unittest
import ast
import textwrap
from typing import Union, List, Any, cast
from pywire.compiler.parser import PyWireParser
from pywire.compiler.codegen.template import TemplateCodegen

class TestHeadCodegen(unittest.TestCase):
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

    def test_head_tag_compilation(self):
        # Now that void tags support />, this source should parse correctly
        source = textwrap.dedent("""
            <head>
                <title>My Title</title>
                <meta name="description" content="Test" />
            </head>
            <div>Body Content</div>
        """).strip()
        
        parser = PyWireParser()
        parsed = parser.parse(source)
        codegen = TemplateCodegen()
        
        # generate_slot_methods should detect <head> and put it in $head slot
        slot_methods, aux_funcs = codegen.generate_slot_methods(
            parsed.template,
            file_id="test_file",
            layout_id="TEST_LAYOUT"
        )
        
        # Check if $head slot is present
        self.assertIn("$head", slot_methods)
        
        # Get the AST for the $head slot method
        head_method_ast = slot_methods["$head"]
        
        # Normalize AST to fix missing line numbers for unparse
        self.normalize_ast(head_method_ast)
        
        # Convert to string to inspect content
        code = ast.unparse(head_method_ast)
        
        # Check for components of the title tag
        self.assertIn("'My Title'", code)
        self.assertIn("'<title'", code)
        self.assertIn("'</title>'", code)
        
        # Check for meta tag components (now that they are correctly parsed)
        self.assertIn("'<meta'", code)
        self.assertIn("'description'", code)
        self.assertIn("'Test'", code)
        
        # Should NOT contain body content
        self.assertNotIn('Body Content', code)
        
        # Check default slot (body content)
        self.assertIn("default", slot_methods)
        default_method_ast = slot_methods["default"]
        self.normalize_ast(default_method_ast)
        default_code = ast.unparse(default_method_ast)
        self.assertIn('Body Content', default_code)
        self.assertNotIn("'<title'", default_code)

if __name__ == "__main__":
    unittest.main()
