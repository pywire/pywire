import ast
import unittest
from typing import Any, List, Union, cast

from pywire.compiler.ast_nodes import (
    EventAttribute,
    InterpolationNode,
    SpecialAttribute,
    TemplateNode,
)
from pywire.compiler.codegen.template import TemplateCodegen


class TestCodegenTemplate(unittest.TestCase):
    def setUp(self) -> None:
        self.codegen = TemplateCodegen()

    def normalize_ast(self, node: Union[ast.AST, List[ast.AST]]) -> Union[ast.AST, List[ast.AST]]:
        """Ensure all nodes have lineno/col_offset for unparse."""
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

    def assert_ast_equal(self, ast_node: Any, expected_code: str) -> None:
        """Helper to compare AST node equal to expected code string."""
        self.normalize_ast(ast_node)

        # Normalize by parsing the expected code
        if isinstance(ast_node, ast.AST):
            generated_code = ast.unparse(ast_node).strip()
            self.assertEqual(generated_code, expected_code)
        elif isinstance(ast_node, list):
            # For list of statements
            generated_code = "\n".join(ast.unparse(n) for n in ast_node).strip()
            self.assertEqual(generated_code, expected_code)
        else:
            self.fail(f"Unexpected AST type: {type(ast_node)}")

    def test_transform_expr_basic(self) -> None:
        # name should become self.name
        expr = "name == 'Admin' and age > 18"
        transformed = self.codegen._transform_expr(expr, local_vars=set())
        self.assert_ast_equal(transformed, "self.name == 'Admin' and self.age > 18")

    def test_transform_expr_with_locals(self) -> None:
        # item is local, should NOT get self. prefix
        expr = "item.name == 'Test'"
        transformed = self.codegen._transform_expr(expr, local_vars={"item"})
        self.assert_ast_equal(transformed, "item.name == 'Test'")

    def test_transform_reactive_expr_auto_call(self) -> None:
        # Parameterless method should be auto-called
        expr = "my_method"
        transformed = self.codegen._transform_reactive_expr(
            expr, local_vars=set(), known_methods={"my_method"}
        )
        self.assert_ast_equal(transformed, "self.my_method()")

    def test_transform_reactive_expr_async(self) -> None:
        # Async method should be awaited
        expr = "get_data()"
        transformed = self.codegen._transform_reactive_expr(
            expr, local_vars=set(), async_methods={"get_data"}
        )
        self.assert_ast_equal(transformed, "await self.get_data()")

    def test_generate_render_method(self) -> None:
        # Interpolation must be wrapped in a TemplateNode with tag=None
        interp_node = InterpolationNode(line=1, column=0, expression="msg")
        text_wrapper = TemplateNode(
            tag=None, special_attributes=[cast(SpecialAttribute, interp_node)], line=1, column=0
        )
        node = TemplateNode(tag="div", children=[text_wrapper], line=1, column=0)

        func_def, aux = self.codegen.generate_render_method([node])

        self.normalize_ast(func_def)
        code = ast.unparse(func_def)
        self.assertIn("async def _render_template(self):", code)
        self.assertIn("parts = []", code)
        self.assertIn("import json", code)
        self.assertIn("parts.append('<div')", code)  # unparse uses single quotes often?
        self.assertIn("parts.append(str(self.msg))", code)
        self.assertIn("parts.append('</div>')", code)
        self.assertIn("return ''.join(parts)", code)

    def test_generate_slot_methods(self) -> None:
        # Node with slot filler: <slot name="header">...</slot>
        node = TemplateNode(
            tag="slot",
            attributes={"name": "header"},
            children=[TemplateNode(tag=None, text_content="Header content", line=1, column=0)],
            line=1,
            column=0,
        )

        slots, aux = self.codegen.generate_slot_methods([node], file_id="test")
        self.assertIn("header", slots)

        # slots["header"] is an AsyncFunctionDef
        func_def = slots["header"]
        self.normalize_ast(func_def)
        code = ast.unparse(func_def)

        self.assertIn("async def _render_slot_fill_header_", code)
        self.assertIn("parts.append('Header content')", code)

    def test_codegen_component_instantiation(self) -> None:
        node = TemplateNode(tag="MyComp", attributes={"title": "Hello"}, line=1, column=0)
        comp_map = {"MyComp": "MyComponent"}
        func_def, _ = self.codegen.generate_render_method([node], component_map=comp_map)

        self.normalize_ast(func_def)
        code = ast.unparse(func_def)
        self.assertIn("MyComponent", code)
        self.assertIn("'title': 'Hello'", code)
        self.assertIn("'__is_component__': True", code)
        self.assertIn("'_style_collector': self._style_collector", code)

    def test_codegen_component_slots(self) -> None:
        child1 = TemplateNode(tag="div", attributes={"slot": "header"}, line=1, column=0)
        child2 = TemplateNode(tag="span", attributes={}, line=1, column=0)
        node = TemplateNode(
            tag="MyComp", attributes={}, children=[child1, child2], line=1, column=0
        )
        comp_map = {"MyComp": "MyComponent"}

        func_def, _ = self.codegen.generate_render_method([node], component_map=comp_map)
        self.normalize_ast(func_def)
        code = ast.unparse(func_def)
        self.assertIn("slots={'header':", code)
        self.assertIn("'default':", code)

    def test_codegen_component_events(self) -> None:
        event_attr = EventAttribute(
            line=1,
            column=0,
            name="@click",
            value="handleClick",
            event_type="click",
            handler_name="handleClick",
            args=[],
            modifiers=[],
        )
        node = TemplateNode(
            tag="MyComp", attributes={}, special_attributes=[event_attr], line=1, column=0
        )
        comp_map = {"MyComp": "MyComponent"}

        func_def, _ = self.codegen.generate_render_method([node], component_map=comp_map)
        self.normalize_ast(func_def)
        code = ast.unparse(func_def)
        self.assertIn("'data-on-click': 'handleClick'", code)

    def test_element_attribute_injection(self) -> None:
        node = TemplateNode(tag="div", attributes={}, line=1, column=0)
        scope_id = "xyz123"
        func_def, _ = self.codegen.generate_render_method([node], scope_id=scope_id)

        self.normalize_ast(func_def)
        code = ast.unparse(func_def)
        self.assertIn("attrs['data-ph-xyz123'] = ''", code)

    def test_scoped_style_rewriting(self) -> None:
        css_content = ".card { color: red; }"
        style_node = TemplateNode(
            tag="style",
            attributes={"scoped": ""},
            line=1,
            column=0,
            children=[TemplateNode(tag=None, text_content=css_content, line=1, column=0)],
        )
        scope_id = "xyz123"

        func_def, _ = self.codegen.generate_render_method([style_node], scope_id=scope_id)
        self.normalize_ast(func_def)
        code = ast.unparse(func_def)
        self.assertIn("self._style_collector.add('xyz123'", code)
        self.assertIn(".card[data-ph-xyz123]", code)


if __name__ == "__main__":
    unittest.main()
