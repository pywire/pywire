"""Bind attribute parser ($bind)."""

from typing import Optional

from pywire.compiler.ast_nodes import BindAttribute, SpecialAttribute
from pywire.compiler.attributes.base import AttributeParser
from pywire.compiler.exceptions import PyWireSyntaxError


class BindAttributeParser(AttributeParser):
    """Parses $bind attribute."""

    def can_parse(self, attr_name: str) -> bool:
        """Check if attribute is $bind."""
        return attr_name == "$bind"

    def parse(
        self, attr_name: str, attr_value: str, line: int, col: int
    ) -> Optional[SpecialAttribute]:
        """Parse $bind attribute."""
        """Parse $bind attribute."""
        if not (attr_value.startswith("{") and attr_value.endswith("}")):
            raise PyWireSyntaxError(
                f"Value for '{attr_name}' must be wrapped in brackets: {attr_name}={{expr}}",
                line=line,
            )

        # Strip brackets
        expr = attr_value[1:-1].strip()

        return BindAttribute(
            name=attr_name,
            value=attr_value,
            variable=expr,
            binding_type=None,
            line=line,
            column=col,
        )
