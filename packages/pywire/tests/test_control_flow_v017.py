import ast
import unittest
import asyncio
from pywire.compiler.parser import PyWireParser
from pywire.compiler.codegen.template import TemplateCodegen
from pywire.compiler.ast_nodes import (
    AwaitAttribute,
    CatchAttribute,
    ElifAttribute,
    ElseAttribute,
    ExceptAttribute,
    FinallyAttribute,
    ForAttribute,
    IfAttribute,
    ThenAttribute,
    TryAttribute,
)

class TestControlFlowV017(unittest.TestCase):
    def setUp(self):
        self.parser = PyWireParser()
        self.codegen = TemplateCodegen()

    def test_if_elif_else_syntax(self):
        source = """
---html---
{$if count > 10}
    <p>Large</p>
{$elif count > 5}
    <p>Medium</p>
{$else}
    <p>Small</p>
{/if}
"""
        ast_nodes = self.parser.parse(source)
        # Find the if node (ignore whitespace)
        if_node = next(n for n in ast_nodes.template if any(isinstance(a, IfAttribute) for a in n.special_attributes))
        self.assertIsNone(if_node.tag)
        
        # Verify elif/else markers in children
        markers = []
        for c in if_node.children:
            for a in c.special_attributes:
                markers.append(a.__class__.__name__)
        self.assertIn("ElifAttribute", markers)
        self.assertIn("ElseAttribute", markers)

    def test_for_multiple_roots(self):
        source = """
---html---
{$for item in items, key=item.id}
    <h1>{item.name}</h1>
    <p>{item.desc}</p>
{/for}
"""
        ast_nodes = self.parser.parse(source)
        for_node = next(n for n in ast_nodes.template if any(isinstance(a, ForAttribute) for a in n.special_attributes))
        
        # Should have 2 elements in children
        elements = [c for c in for_node.children if c.tag]
        self.assertEqual(len(elements), 2)
        
        for_attr = next(a for a in for_node.special_attributes if isinstance(a, ForAttribute))
        self.assertEqual(for_attr.key, "item.id")
        self.assertEqual(for_attr.iterable, "items")

    def test_try_except_finally(self):
        source = """
---html---
{$try}
    {risky()}
{$except ValueError as e}
    <p>Error: {e}</p>
{$finally}
    <p>Done</p>
{/try}
"""
        ast_nodes = self.parser.parse(source)
        try_node = next(n for n in ast_nodes.template if any(isinstance(a, TryAttribute) for a in n.special_attributes))
        markers = []
        for c in try_node.children:
            for a in c.special_attributes:
                markers.append(a.__class__.__name__)
        
        self.assertIn("ExceptAttribute", markers)
        self.assertIn("FinallyAttribute", markers)

    def test_await_then_catch(self):
        source = """
---html---
{$await fetch()}
    <p>Loading...</p>
{$then res}
    <p>Result: {res}</p>
{$catch err}
    <p>Failed: {err}</p>
{/await}
"""
        ast_nodes = self.parser.parse(source)
        await_node = next(n for n in ast_nodes.template if any(isinstance(a, AwaitAttribute) for a in n.special_attributes))
        markers = []
        for c in await_node.children:
            for a in c.special_attributes:
                markers.append(a.__class__.__name__)
        
        self.assertIn("ThenAttribute", markers)
        self.assertIn("CatchAttribute", markers)

    def test_nested_complex(self):
        source = """
---html---
<div>
    {$for i in range(2), key=i}
        {$if i == 0}
            <span>Zero</span>
        {$else}
            <span>One</span>
        {/if}
    {/for}
</div>
"""
        ast_nodes = self.parser.parse(source)
        div = next(n for n in ast_nodes.template if n.tag == "div")
        self.assertEqual(div.tag, "div")
        
        for_node = next(c for c in div.children if any(isinstance(a, ForAttribute) for a in c.special_attributes))
        self.assertIsNone(for_node.tag)

    def test_if_elif_else_codegen(self):
        source = """
---html---
{$if cond}
    A
{$else}
    B
{/if}
"""
        ast_nodes = self.parser.parse(source)
        func_def, _ = self.codegen.generate_render_method(ast_nodes.template)
        ast.fix_missing_locations(func_def)
        code = ast.unparse(func_def)
        
        self.assertIn("if self.cond:", code)
        self.assertIn("A", code)
        self.assertIn("else:", code)
        self.assertIn("B", code)
        self.assertIn("parts.append", code)
        self.assertIn("'.join(parts)", code)

    def test_for_multi_root_codegen(self):
        source = """
---html---
{$for i in items, key=i}
    <h1>{i}</h1>
    <p>text</p>
{/for}
"""
        ast_nodes = self.parser.parse(source)
        func_def, _ = self.codegen.generate_render_method(ast_nodes.template)
        ast.fix_missing_locations(func_def)
        code = ast.unparse(func_def)
        
        # Check that both h1 and p are inside the loop
        self.assertIn("async for i in ensure_async_iterator(self.items):", code)
        self.assertIn("<h1", code) # h1
        self.assertIn("<p", code) # p
        self.assertIn("text", code) # p content

    def test_try_except_codegen(self):
        source = """
---html---
{$try}
    {risky()}
{$except ValueError as e}
    Error
{/try}
"""
        ast_nodes = self.parser.parse(source)
        func_def, _ = self.codegen.generate_render_method(ast_nodes.template)
        ast.fix_missing_locations(func_def)
        code = ast.unparse(func_def)
        
        self.assertIn("try:", code)
        self.assertIn("except ValueError as e:", code)
        self.assertIn("Error", code)

    def test_await_then_codegen(self):
        source = """
---html---
{$await fetch()}
{$then res}
    {res}
{/await}
"""
        ast_nodes = self.parser.parse(source)
        func_def, _ = self.codegen.generate_render_method(ast_nodes.template)
        ast.fix_missing_locations(func_def)
        code = ast.unparse(func_def)
        
        self.assertIn("_resolve_await", code)
        self.assertIn("asyncio.create_task", code)
        self.assertIn("self.fetch()", code)

    def test_reactive_var_not_control_flow(self):
        # Ensure {$count} is NOT incorrectly converted to a pywire-count tag
        # but is treated as a reactive interpolation.
        from pywire.compiler.ast_nodes import InterpolationNode, EventAttribute
        template = """
        <div>
            <button @click={$count += 1}>{$count}</button>
            {$if count > 0}
                <p>Positive</p>
            {/if}
        </div>
        """
        parsed = self.parser.parse(template)
        
        # Check button children
        div = next(n for n in parsed.template if n.tag == "div")
        button = next(n for n in div.children if n.tag == "button")
        
        # The button child should contain an InterpolationNode for $count
        self.assertEqual(len(button.children), 1)
        self.assertIsInstance(button.children[0].special_attributes[0], InterpolationNode)
        self.assertEqual(button.children[0].special_attributes[0].expression, "$count")
        
        # The event handler should be an EventAttribute
        self.assertIsInstance(button.special_attributes[0], EventAttribute)
        self.assertEqual(button.special_attributes[0].handler_name, "$count += 1")
        
        # The if block should be correctly parsed
        from pywire.compiler.ast_nodes import IfAttribute
        if_node = next(n for n in div.children if any(isinstance(a, IfAttribute) for a in n.special_attributes))
        self.assertIsInstance(if_node.special_attributes[0], IfAttribute)

if __name__ == "__main__":
    unittest.main()
