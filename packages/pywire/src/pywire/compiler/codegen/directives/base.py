"""Base directive code generator."""

import ast
from abc import ABC, abstractmethod
from typing import List

from pywire.compiler.ast_nodes import Directive


class DirectiveCodegen(ABC):
    """Base class for directive code generation."""

    @abstractmethod
    def generate(self, directive: Directive) -> List[ast.stmt]:
        """Generate AST statements for directive."""
        pass
