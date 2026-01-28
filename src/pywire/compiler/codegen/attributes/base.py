"""Base attribute code generator."""

import ast
from abc import ABC, abstractmethod
from typing import Optional

from pywire.compiler.ast_nodes import SpecialAttribute


class AttributeCodegen(ABC):
    """Base class for attribute code generation."""

    @abstractmethod
    def generate_html(self, attr: SpecialAttribute) -> str:
        """Generate HTML attributes for client."""

    @abstractmethod
    def generate_handler(self, attr: SpecialAttribute) -> Optional[ast.FunctionDef]:
        """Generate server-side handler if needed. Returns None if user defines it."""
