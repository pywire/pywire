import unittest
from pywire.compiler.parser import PyWireParser, PyWireSyntaxError
from pywire.compiler.codegen.template import TemplateCodegen
from pywire.compiler.ast_nodes import IfAttribute, ShowAttribute, ForAttribute

class TestControlFlow(unittest.TestCase):
    def test_if_block(self):
        source = """
---html---
<$if condition="True">
    <div>Found</div>
</$if>
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

    def test_if_block_shorthand(self):
        source = """
---html---
<$if {cond}>
    <div>Found</div>
</$if>
"""
        parser = PyWireParser()
        ast = parser.parse(source)
        node = ast.template[0]
        if_attrs = [a for a in node.special_attributes if isinstance(a, IfAttribute)]
        self.assertEqual(len(if_attrs), 1)
        # Shorthand {cond} -> condition="cond"
        self.assertEqual(if_attrs[0].condition, "cond")

    def test_show_block(self):
        source = """
---html---
<$show condition="visible">
  Content
</$show>
"""
        parser = PyWireParser()
        ast = parser.parse(source)
        node = ast.template[0]
        self.assertIsNone(node.tag)
        show_attrs = [a for a in node.special_attributes if isinstance(a, ShowAttribute)]
        self.assertEqual(len(show_attrs), 1)
        self.assertEqual(show_attrs[0].condition, "visible")

    def test_for_block_valid(self):
        source = """
---html---
<$for $for="{item in items}">
    <div>{item}</div>
</$for>
"""
        # Note: $for attribute is preserved. 
        # My logic checks ForAttribute.
        # parser._parse_attributes parses $for="..." -> ForAttribute.
        
        parser = PyWireParser()
        ast = parser.parse(source)
        node = ast.template[0]
        self.assertIsNone(node.tag)
        for_attrs = [a for a in node.special_attributes if isinstance(a, ForAttribute)]
        self.assertEqual(len(for_attrs), 1)
        # check ForAttribute fields
        # "item in items" -> loop_vars="item", iterable="items" (if properly parsed)
        self.assertEqual(for_attrs[0].iterable, "items")

    def test_for_block_single_root_valid(self):
        source = """
---html---
<$for $for="{i in x}">
   <!-- comment -->
   <div>Single Root</div>
</$for>
"""
        parser = PyWireParser()
        parser.parse(source) # Should pass

    def test_for_block_invalid_multi_root(self):
        source = """
---html---
<$for $for="{i in x}">
   <div>Root 1</div>
   <div>Root 2</div>
</$for>
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
