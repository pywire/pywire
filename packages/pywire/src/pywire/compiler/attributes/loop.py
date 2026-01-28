"""Loop attribute parsers ($for, $key)."""

from typing import Optional

from pywire.compiler.ast_nodes import ForAttribute, KeyAttribute, SpecialAttribute
from pywire.compiler.attributes.base import AttributeParser
from pywire.compiler.exceptions import PyWireSyntaxError


class LoopAttributeParser(AttributeParser):
    """Parses $for attributes."""

    def can_parse(self, attr_name: str) -> bool:
        """Check if attribute is $for."""
        return attr_name == "$for"

    def parse(
        self, attr_name: str, attr_value: str, line: int, col: int
    ) -> Optional[SpecialAttribute]:
        """Parse $for attribute."""
        if not (attr_value.startswith("{") and attr_value.endswith("}")):
            raise PyWireSyntaxError(
                f"Value for '{attr_name}' must be wrapped in brackets: "
                f"{attr_name}={{item in items}}",
                line=line,
            )

        expr = attr_value[1:-1].strip()
        # Parse "item in items" or "key, value in items"
        parts = expr.split(" in ", 1)
        if len(parts) != 2:
            # We don't raise error here, just return nothing or let it be
            # handled as valid attribute?
            # Ideally validation happens here.
            # But creating AST node blindly is safer if we want to defer errors.
            # But "item in items" is pretty fundamental.
            raise ValueError(
                f"Invalid $for syntax at line {line}: '{attr_value}'. Expected 'item in items'."
            )

        loop_vars = parts[0].strip()
        iterable = parts[1].strip()

        return ForAttribute(
            name=attr_name,
            value=attr_value,
            is_template_tag=False,  # Populated later
            loop_vars=loop_vars,
            iterable=iterable,
            line=line,
            column=col,
        )


class KeyAttributeParser(AttributeParser):
    """Parses $key attributes."""

    def can_parse(self, attr_name: str) -> bool:
        """Check if attribute is $key."""
        return attr_name == "$key"

    def parse(
        self, attr_name: str, attr_value: str, line: int, col: int
    ) -> Optional[SpecialAttribute]:
        """Parse $key attribute."""
        if not (attr_value.startswith("{") and attr_value.endswith("}")):
            raise PyWireSyntaxError(
                f"Value for '{attr_name}' must be wrapped in brackets: {attr_name}={{expr}}",
                line=line,
            )

        expr = attr_value[1:-1].strip()
        return KeyAttribute(name=attr_name, value=attr_value, expr=expr, line=line, column=col)
