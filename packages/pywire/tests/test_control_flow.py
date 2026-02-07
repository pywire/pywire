import unittest
from pywire.compiler.parser import PyWireParser, PyWireSyntaxError
from pywire.compiler.codegen.template import TemplateCodegen
from pywire.compiler.ast_nodes import IfAttribute, ShowAttribute, ForAttribute

class TestControlFlow(unittest.TestCase):
    def test_if_block(self):
        source = """
---html---
{$if True}
    <div>Found</div>
{/if}
"""
        parser = PyWireParser()
        ast = parser.parse(source)
        node = ast.template[0]
        
        # Check node type (tag=None -> template wrapper)
        self.assertIsNone(node.tag)
        # Check IfAttribute
        if_attrs = [a for a in node.special_attributes if isinstance(a, IfAttribute)]
        self.assertEqual(len(if_attrs), 1)
        self.assertEqual(if_attrs[0].condition, "True")
        
        # Check child exists (ignoring whitespace)
        real_children = [c for c in node.children if c.tag]
        self.assertEqual(len(real_children), 1) # div

    def test_html_block(self):
        source = """
---html---
{$html "<b>Raw</b>"}
"""
        parser = PyWireParser()
        ast = parser.parse(source)
        node = ast.template[0]
        self.assertIsNone(node.tag)
        from pywire.compiler.ast_nodes import InterpolationNode
        interp_attrs = [a for a in node.special_attributes if isinstance(a, InterpolationNode)]
        self.assertEqual(len(interp_attrs), 1)
        self.assertTrue(interp_attrs[0].is_raw)
        self.assertEqual(interp_attrs[0].expression, '"<b>Raw</b>"')

    def test_for_block_valid(self):
        source = """
---html---
{$for item in items}
    <div>{item}</div>
{/for}
"""
        parser = PyWireParser()
        ast = parser.parse(source)
        node = ast.template[0]
        self.assertIsNone(node.tag)
        for_attrs = [a for a in node.special_attributes if isinstance(a, ForAttribute)]
        self.assertEqual(len(for_attrs), 1)
        self.assertEqual(for_attrs[0].iterable, "items")

    def test_for_block_single_root_valid(self):
        source = """
---html---
{$for i in x}
   <!-- comment -->
   <div>Single Root</div>
{/for}
"""
        parser = PyWireParser()
        parser.parse(source) # Should pass

    def test_for_block_invalid_multi_root(self):
        source = """
---html---
{$for i in x}
   <div>Root 1</div>
   <div>Root 2</div>
{/for}
"""
        parser = PyWireParser()
        with self.assertRaises(PyWireSyntaxError) as cm:
             parser.parse(source)
        self.assertIn("must have exactly one root element", str(cm.exception))

    def test_for_else(self):
        source = """
---html---
<ul>
    {$for item in items}
        <li>{item}</li>
    {$else}
        <li class="empty-state">Empty</li>
    {/for}
</ul>
"""
        parser = PyWireParser()
        parsed = parser.parse(source)
        
        from pywire.compiler.codegen.template import TemplateCodegen
        import ast
        
        codegen = TemplateCodegen()
        body = []
        # Simulate items is empty
        codegen._add_node(parsed.template[0], body, local_vars={"items"})
        
        # Verify AST contains the loop_any flag and If block
        dump = "\n".join(ast.dump(s) for s in body)
        self.assertIn("_loop_any", dump)
        self.assertIn("AsyncFor", dump)
        self.assertIn("If(test=UnaryOp(op=Not()", dump)

    def test_keyed_for_multi_root(self):
        source = """
---html---
<ul>
    {$for key, val in items.items(), key=key}
        <dt>{key}</dt>
        <dd>{val}</dd>
    {/for}
</ul>
"""
        parser = PyWireParser()
        parser.parse(source) # Should pass

if __name__ == "__main__":
    unittest.main()
