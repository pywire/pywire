import ast
import unittest

from typing import Any, List, Union, cast

from pywire.compiler.ast_nodes import (
    EventAttribute,
    InterpolationNode,
    ReactiveAttribute,
    SpecialAttribute,
    TemplateNode,
)
from pywire.compiler.codegen.template import TemplateCodegen


class TestCodegenTemplate(unittest.TestCase):
    def setUp(self) -> None:
        self.codegen = TemplateCodegen()

    def normalize_ast(
        self, node: Union[ast.AST, List[ast.AST]]
    ) -> Union[ast.AST, List[ast.AST]]:
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

    def test_transform_expr_list_comp_target_not_promoted(self) -> None:
        # Regression: comprehension target was being rewritten to ``self.c``,
        # leaking the last loop value onto the page instance and triggering
        # session-serializer warnings ("Skipping non-serializable attr 'c'").
        expr = "[(c.type, c.value) for c in items]"
        transformed = self.codegen._transform_expr(expr, local_vars=set())
        self.assert_ast_equal(
            transformed,
            "[(c.type, c.value) for c in self.items]",
        )

    def test_transform_expr_dict_comp_target_not_promoted(self) -> None:
        expr = "{c.type: c.value for c in items if c.type != 'sub'}"
        transformed = self.codegen._transform_expr(expr, local_vars=set())
        self.assert_ast_equal(
            transformed,
            "{c.type: c.value for c in self.items if c.type != 'sub'}",
        )

    def test_transform_expr_nested_comp_target_not_promoted(self) -> None:
        expr = "[(a, b) for a in xs for b in ys]"
        transformed = self.codegen._transform_expr(expr, local_vars=set())
        self.assert_ast_equal(
            transformed,
            "[(a, b) for a in self.xs for b in self.ys]",
        )

    def test_transform_expr_comp_tuple_unpack_not_promoted(self) -> None:
        expr = "[k for (k, v) in items]"
        transformed = self.codegen._transform_expr(expr, local_vars=set())
        self.assert_ast_equal(
            transformed,
            "[k for k, v in self.items]",
        )

    def test_transform_expr_lambda_arg_not_promoted(self) -> None:
        expr = "(lambda x: x + 1)(value)"
        transformed = self.codegen._transform_expr(expr, local_vars=set())
        self.assert_ast_equal(
            transformed,
            "(lambda x: x + 1)(self.value)",
        )

    def test_transform_reactive_expr_auto_call(self) -> None:
        # Parameterless method should be auto-called
        expr = "my_method"
        transformed = self.codegen._transform_reactive_expr(
            expr, local_vars=set(), known_methods={"my_method": 0}, cached=False
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
            tag=None,
            special_attributes=[cast(SpecialAttribute, interp_node)],
            line=1,
            column=0,
        )
        node = TemplateNode(tag="div", children=[text_wrapper], line=1, column=0)

        func_def, aux = self.codegen.generate_render_method([node])

        self.normalize_ast(func_def)
        code = ast.unparse(func_def)
        self.assertIn("async def _render_template(self):", code)
        self.assertIn("parts = []", code)
        self.assertIn("import json", code)
        self.assertIn("parts.append(await self._render_region_r1())", code)
        self.assertIn("return ''.join(parts)", code)

    def test_document_root_elements_do_not_become_regions(self) -> None:
        interp_node = InterpolationNode(line=1, column=0, expression="msg")
        text_wrapper = TemplateNode(
            tag=None,
            special_attributes=[cast(SpecialAttribute, interp_node)],
            line=1,
            column=0,
        )
        dynamic_div = TemplateNode(tag="div", children=[text_wrapper], line=1, column=0)
        body = TemplateNode(tag="body", children=[dynamic_div], line=1, column=0)
        head = TemplateNode(
            tag="head",
            children=[
                TemplateNode(
                    tag="meta", attributes={"charset": "utf-8"}, line=1, column=0
                )
            ],
            line=1,
            column=0,
        )
        html = TemplateNode(tag="html", children=[head, body], line=1, column=0)

        func_def, aux = self.codegen.generate_render_method([html])
        self.normalize_ast(func_def)
        self.normalize_ast(aux)
        main_code = ast.unparse(func_def)
        aux_code = "\n".join(ast.unparse(fn) for fn in aux)

        # Ensure document-level tags are rendered inline (not as the region target).
        self.assertIn("parts.append('<html')", main_code)
        self.assertIn("parts.append('<head')", main_code)
        self.assertIn("parts.append('<body')", main_code)

        # Dynamic child inside body should still get a region.
        self.assertIn("parts.append(await self._render_region_r1())", main_code)
        self.assertIn("attrs['data-pw-region'] = 'r1'", aux_code)

    def test_codegen_component_instantiation(self) -> None:
        node = TemplateNode(
            tag="MyComp", attributes={"title": "Hello"}, line=1, column=0
        )
        comp_map = {"MyComp": "MyComponent"}
        func_def, _ = self.codegen.generate_render_method(
            [node], component_map=comp_map
        )

        self.normalize_ast(func_def)
        code = ast.unparse(func_def)
        self.assertIn("MyComponent", code)
        self.assertIn("'title': 'Hello'", code)
        self.assertIn("'__is_component__': True", code)
        self.assertIn("'_style_collector': self._style_collector", code)

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
            tag="MyComp",
            attributes={},
            special_attributes=[event_attr],
            line=1,
            column=0,
        )
        comp_map = {"MyComp": "MyComponent"}

        func_def, _ = self.codegen.generate_render_method(
            [node], component_map=comp_map
        )
        self.normalize_ast(func_def)
        code = ast.unparse(func_def)
        # Component events are emitted as `on_{event}` kwargs so they
        # match the `on_click` / `on_submit` convention in @props classes
        # and don't collide with same-named @expose methods.
        self.assertIn("'on_click': self.handleClick", code)
        self.assertIn("self._resolve_component(", code)

    def test_codegen_form_extracts_field_rules(self) -> None:
        referral_required = ReactiveAttribute(
            line=1,
            column=0,
            name="required",
            value="{has_referral}",
            expr="has_referral",
        )
        input_node = TemplateNode(
            tag="input",
            attributes={
                "name": "age",
                "type": "number",
                "min": "18",
                "max": "100",
                "step": "1",
                "required": "",
            },
            line=1,
            column=0,
        )
        referral_node = TemplateNode(
            tag="input",
            attributes={
                "name": "referral_code",
                "pattern": "^[A-Z0-9]{6,12}$",
            },
            special_attributes=[referral_required],
            line=2,
            column=0,
        )
        form_node = TemplateNode(
            tag="Form",
            attributes={},
            children=[input_node, referral_node],
            line=1,
            column=0,
        )

        func_def, _ = self.codegen.generate_render_method(
            [form_node], known_globals={"has_referral"}
        )
        self.normalize_ast(func_def)
        code = ast.unparse(func_def)

        self.assertIn("'_field_rules':", code)
        self.assertIn(
            "'age': {'required': True, 'min_value': '18', 'max_value': '100', 'step': '1', 'input_type': 'number'}",
            code,
        )
        self.assertIn(
            "'referral_code': {'pattern': '^[A-Z0-9]{6,12}$', 'required': self.has_referral}",
            code,
        )

    def test_codegen_form_extracts_file_field_rules(self) -> None:
        file_node = TemplateNode(
            tag="input",
            attributes={
                "name": "avatar",
                "type": "file",
                "accept": "image/*,.png,.jpg",
                "multiple": "",
                "data-max-size": "2097152",
                "data-min-size": "1024",
                "data-max-files": "3",
                "data-allowed-names": "^avatar_.*\\.(png|jpg)$",
            },
            line=1,
            column=0,
        )
        form_node = TemplateNode(
            tag="Form",
            attributes={},
            children=[file_node],
            line=1,
            column=0,
        )

        func_def, _ = self.codegen.generate_render_method([form_node])
        self.normalize_ast(func_def)
        code = ast.unparse(func_def)

        self.assertIn("'_field_rules':", code)
        self.assertIn("'avatar':", code)
        self.assertIn("'input_type': 'file'", code)
        self.assertIn("'allowed_types': ['image/*', '.png', '.jpg']", code)
        self.assertIn("'multiple': True", code)
        self.assertIn("'max_size': 2097152", code)
        self.assertIn("'min_size': 1024", code)
        self.assertIn("'max_files': 3", code)
        self.assertIn("'allowed_names': '^avatar_.*\\\\.(png|jpg)$'", code)

    def test_codegen_form_extracts_file_input_component_rules(self) -> None:
        file_component_node = TemplateNode(
            tag="FileInput",
            attributes={
                "name": "avatar",
                "accept": "image/*,.png",
                "multiple": "",
                "max_size": "2097152",
                "min_size": "1024",
                "max_files": "3",
                "allowed_names": "^avatar_.*\\.(png)$",
            },
            line=1,
            column=0,
        )
        form_node = TemplateNode(
            tag="Form",
            attributes={},
            children=[file_component_node],
            line=1,
            column=0,
        )

        func_def, _ = self.codegen.generate_render_method([form_node])
        self.normalize_ast(func_def)
        code = ast.unparse(func_def)

        self.assertIn("'_field_rules':", code)
        self.assertIn("'avatar':", code)
        self.assertIn("'input_type': 'file'", code)
        self.assertIn("'allowed_types': ['image/*', '.png']", code)
        self.assertIn("'multiple': True", code)
        self.assertIn("'max_size': 2097152", code)
        self.assertIn("'min_size': 1024", code)
        self.assertIn("'max_files': 3", code)
        self.assertIn("'allowed_names': '^avatar_.*\\\\.(png)$'", code)

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
            children=[
                TemplateNode(tag=None, text_content=css_content, line=1, column=0)
            ],
        )
        scope_id = "xyz123"

        func_def, _ = self.codegen.generate_render_method(
            [style_node], scope_id=scope_id
        )
        self.normalize_ast(func_def)
        code = ast.unparse(func_def)
        self.assertIn("self._style_collector.add('xyz123'", code)
        self.assertIn(".card[data-ph-xyz123]", code)

    def test_import_prefixing_prevention(self) -> None:
        # Test that names in known_imports are not prefixed with self.
        node = TemplateNode(
            tag=None, text_content="{{ json.dumps(obj) }}", line=1, column=0
        )
        known_imports = {"json"}
        known_globals = {"obj"}

        func_def, _ = self.codegen.generate_render_method(
            [node], known_globals=known_globals, known_imports=known_imports
        )
        self.normalize_ast(func_def)
        code = ast.unparse(func_def)

        # Should contain json.dumps(self.obj), NOT self.json.dumps(self.obj)
        self.assertIn("json.dumps(self.obj)", code)
        self.assertNotIn("self.json.dumps", code)


if __name__ == "__main__":
    unittest.main()
