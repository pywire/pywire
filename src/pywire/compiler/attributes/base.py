"""Base attribute parser."""

from abc import ABC, abstractmethod
from typing import Optional

from pywire.compiler.ast_nodes import SpecialAttribute


class AttributeParser(ABC):
    """Base class for parsing special attributes - extensible for $, @, : types."""

    PREFIX: str  # '@', '$', or ':'

    @abstractmethod
    def can_parse(self, attr_name: str) -> bool:
        """Check if this parser can handle the attribute."""
        return attr_name.startswith(self.PREFIX)

    @abstractmethod
    def parse(
        self, attr_name: str, attr_value: str, line: int, col: int
    ) -> Optional[SpecialAttribute]:
        """Parse attribute. Returns None if not applicable."""
        pass
