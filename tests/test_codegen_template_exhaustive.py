import ast
import unittest
from typing import Any, List, cast

from pywire.compiler.ast_nodes import (
    BindAttribute,
    EventAttribute,
    ForAttribute,
    IfAttribute,
    ReactiveAttribute,
    ShowAttribute,
    TemplateNode,
)
from pywire.compiler.codegen.template import TemplateCodegen


class TestCodegenTemplateExhaustive(unittest.TestCase):
    def setUp(self) -> None:
        self.codegen = TemplateCodegen()

    def normalize_ast(self, node: ast.AST | list[ast.AST]) -> ast.AST | list[ast.AST]:
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

    def assert_code_in(self, snippet: str, statements: List[ast.stmt]) -> None:
        """Helper to check if snippet exists in unparsed statements."""
        self.normalize_ast(cast(Any, statements))
        full_code = "\n".join(ast.unparse(s) for s in statements)
        self.assertIn(snippet, full_code)

    def test_add_node_for_loop(self) -> None:
        # <template $for={item in items}><span>{item}</span></template>
        for_attr = ForAttribute(
            name="$for",
            value="item in items",
            is_template_tag=True,
            loop_vars="item",
            iterable="items",
            line=1,
            column=0,
        )
        span = TemplateNode(tag="span", attributes={}, line=1, column=0)
        node = TemplateNode(
            tag="template", special_attributes=[for_attr], children=[span], line=1, column=0
        )

        lines: list[ast.stmt] = []
        self.codegen._add_node(node, lines)

        self.assert_code_in("async for item in ensure_async_iterator(self.items):", lines)
        # Check that child node was added with increased indent
        self.assert_code_in("parts.append('<span')", lines)

    def test_add_node_if_condition(self) -> None:
        # <div $if={show_me}>Content</div>
        if_attr = IfAttribute(name="$if", value="show_me", condition="show_me", line=1, column=0)
        node = TemplateNode(tag="div", special_attributes=[if_attr], children=[], line=1, column=0)

        lines: list[ast.stmt] = []
        self.codegen._add_node(node, lines)
        self.assert_code_in("if self.show_me:", lines)

    def test_add_node_bind_checkbox(self) -> None:
        # <input type="checkbox" $bind={is_active}>
        bind = BindAttribute(
            name="$bind",
            value="is_active",
            variable="is_active",
            binding_type="property",
            line=1,
            column=0,
        )
        node = TemplateNode(
            tag="input",
            attributes={"type": "checkbox"},
            special_attributes=[bind],
            line=1,
            column=0,
        )

        lines: list[ast.stmt] = []
        self.codegen._add_node(node, lines)
        # Check for checked binding logic
        self.assert_code_in("if self.is_active:", lines)
        self.assert_code_in("attrs['checked'] = ''", lines)

    def test_add_node_bind_select(self) -> None:
        # <select $bind={selected_val}><option value="1">One</option></select>
        bind = BindAttribute(
            name="$bind",
            value="selected_val",
            variable="selected_val",
            binding_type="property",
            line=1,
            column=0,
        )
        option = TemplateNode(
            tag="option", attributes={"value": "1"}, children=[], line=1, column=0
        )
        node = TemplateNode(
            tag="select",
            attributes={},
            special_attributes=[bind],
            children=[option],
            line=1,
            column=0,
        )

        lines: list[ast.stmt] = []
        self.codegen._add_node(node, lines)
        # Check that option has selected logic based on bound_var
        self.assert_code_in(
            "if 'value' in attrs and str(attrs['value']) == str(self.selected_val):", lines
        )
        self.assert_code_in("attrs['selected'] = ''", lines)

    def test_add_node_reactive_boolean(self) -> None:
        # <button disabled={is_disabled}>Click</button>
        reactive = ReactiveAttribute(
            name="disabled", value="is_disabled", expr="is_disabled", line=1, column=0
        )
        node = TemplateNode(tag="button", special_attributes=[reactive], line=1, column=0)

        lines: list[ast.stmt] = []
        self.codegen._add_node(node, lines)
        # Should handle HTML boolean attribute (presence/absence)
        self.assert_code_in("if _r_val is True:", lines)
        self.assert_code_in("attrs['disabled'] = ''", lines)

    def test_add_node_show_attribute(self) -> None:
        # <div $show={is_visible}>...</div>
        show = ShowAttribute(
            name="$show", value="is_visible", condition="is_visible", line=1, column=0
        )
        node = TemplateNode(tag="div", special_attributes=[show], line=1, column=0)

        lines: list[ast.stmt] = []
        self.codegen._add_node(node, lines)
        self.assert_code_in("if not self.is_visible:", lines)
        self.assert_code_in("attrs['style'] = attrs.get('style', '') + '; display: none'", lines)

    def test_add_node_event_with_args(self) -> None:
        # <button @click={delete_user(user.id)}>Delete</button>
        event = EventAttribute(
            name="@click",
            value="delete_user(user.id)",
            event_type="click",
            handler_name="delete_user",
            args=["user.id"],
            line=1,
            column=0,
        )
        node = TemplateNode(tag="button", special_attributes=[event], line=1, column=0)

        lines: list[ast.stmt] = []
        self.codegen._add_node(node, lines, local_vars={"user"})
        # Should encode arguments to data-arg-0
        self.assert_code_in("attrs['data-arg-0'] = json.dumps(user.id)", lines)


if __name__ == "__main__":
    unittest.main()
