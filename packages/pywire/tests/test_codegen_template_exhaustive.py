import ast
import unittest
from typing import Any, List, cast

from pywire.compiler.ast_nodes import (
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
        self.codegen._add_node(node, lines, enable_regions=False)

        self.assert_code_in("async for item in ensure_async_iterator(self.items):", lines)
        # Check that child node was added with increased indent
        self.assert_code_in("parts.append('<span')", lines)

    def test_add_node_if_condition(self) -> None:
        # <div $if={show_me}>Content</div>
        if_attr = IfAttribute(name="$if", value="show_me", condition="show_me", line=1, column=0)
        node = TemplateNode(tag="div", special_attributes=[if_attr], children=[], line=1, column=0)

        lines: list[ast.stmt] = []
        self.codegen._add_node(node, lines, enable_regions=False)
        self.assert_code_in("if self.show_me:", lines)

    def test_add_node_reactive_boolean(self) -> None:
        # <button disabled={is_disabled}>Click</button>
        reactive = ReactiveAttribute(
            name="disabled", value="is_disabled", expr="is_disabled", line=1, column=0
        )
        node = TemplateNode(tag="button", special_attributes=[reactive], line=1, column=0)

        lines: list[ast.stmt] = []
        self.codegen._add_node(node, lines, enable_regions=False)
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
        self.codegen._add_node(node, lines, enable_regions=False)
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
