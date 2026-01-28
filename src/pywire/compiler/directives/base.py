"""Base directive parser."""

from abc import ABC, abstractmethod
from typing import Optional

from pywire.compiler.ast_nodes import Directive


class DirectiveParser(ABC):
    """Base class for parsing directives - extensible for new directives."""

    @abstractmethod
    def can_parse(self, line: str) -> bool:
        """Check if this parser can handle the given line."""
        pass

    @abstractmethod
    def parse(self, line: str, line_num: int, col_num: int) -> Optional[Directive]:
        """Parse directive from line. Returns None if not applicable."""
        pass
