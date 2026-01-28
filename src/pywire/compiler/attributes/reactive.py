"""Reactive attribute parser (:attr)."""

from typing import Optional

from pywire.compiler.ast_nodes import ReactiveAttribute, SpecialAttribute
from pywire.compiler.attributes.base import AttributeParser


class ReactiveAttributeParser(AttributeParser):
    """Parses reactive attributes starting with :"""

    def can_parse(self, attr_name: str) -> bool:
        """
        Check if attribute starts with : but is NOT a directive like :class (if we had those)
        or other special chars.
        Actually requirements say: ":attribute"
        "it explicitly does NOT support framework attributes like anything starting with @ or $"
        But @ and $ are handled by other parsers anyway.
        So we just check for starting with :
        """
        # Disabled: :prop="val" syntax is deprecated.
        # Reactive attributes must use prop={expr} syntax which is handled by parser fallback.
        return False

    def parse(
        self, attr_name: str, attr_value: str, line: int, col: int
    ) -> Optional[SpecialAttribute]:
        """Parse attr={expr}"."""
        # Strip the leading :
        real_name = attr_name[1:]

        return ReactiveAttribute(
            name=real_name, value=attr_value, expr=attr_value, line=line, column=col
        )
