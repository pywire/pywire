"""Layout directive parser."""

import ast
import re
from typing import Optional

from pywire.compiler.ast_nodes import LayoutDirective
from pywire.compiler.directives.base import DirectiveParser


class LayoutDirectiveParser(DirectiveParser):
    """Parses !layout directives."""

    PATTERN = re.compile(r"^!layout\s+(.+)$", re.DOTALL)

    def can_parse(self, line: str) -> bool:
        """Check if line starts with !layout."""
        return line.strip().startswith("!layout")

    def parse(self, line: str, line_num: int, col_num: int) -> Optional[LayoutDirective]:
        """Parse !layout "path/to/layout" directive."""
        match = self.PATTERN.match(line.strip())
        if not match:
            return None

        path_str = match.group(1).strip()
        if not path_str:
            return None

        try:
            # Parse python string
            # We expect a simple string literal
            expr_ast = ast.parse(path_str, mode="eval")

            if isinstance(expr_ast.body, ast.Constant) and isinstance(expr_ast.body.value, str):
                return LayoutDirective(
                    name="layout", layout_path=expr_ast.body.value, line=line_num, column=col_num
                )

            return None
        except (SyntaxError, ValueError, AttributeError):
            return None
