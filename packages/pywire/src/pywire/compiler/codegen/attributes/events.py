"""Event attribute code generator."""

import ast
from typing import Optional

from pywire.compiler.ast_nodes import EventAttribute, SpecialAttribute
from pywire.compiler.codegen.attributes.base import AttributeCodegen


class EventAttributeCodegen(AttributeCodegen):
    """Generates event handler hookup for @click."""

    def generate_html(self, attr: SpecialAttribute) -> str:
        """Generate HTML data attribute for event."""
        assert isinstance(attr, EventAttribute)
        # @click.prevent={handler} → data-on-click="handler" data-modifiers-click="prevent"
        attrs = [f'data-on-{attr.event_type}="{attr.handler_name}"']
        if attr.modifiers:
            attrs.append(
                f'data-modifiers-{attr.event_type}="{" ".join(attr.modifiers)}"'
            )

        # Field mask for bandwidth optimization
        if attr.field_mask is not None:
            field_list = ",".join(sorted(attr.field_mask))
            attrs.append(f'data-pw-fields-{attr.event_type}="{field_list}"')

        # Lifted arguments support
        if hasattr(attr, "args") and attr.args:
            for i, arg in enumerate(attr.args):
                # We need to escape quotes in the argument value for HTML
                escaped_arg = str(arg).replace('"', "&quot;")
                attrs.append(f'data-arg-{i}="{escaped_arg}"')

        return " ".join(attrs)

    def generate_handler(self, attr: SpecialAttribute) -> Optional[ast.FunctionDef]:
        """Generate handler method AST."""
        assert isinstance(attr, EventAttribute)
        return None
