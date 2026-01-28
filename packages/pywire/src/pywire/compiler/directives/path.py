"""Path directive parser."""

import ast
import re
from typing import Dict, Optional

from pywire.compiler.ast_nodes import PathDirective
from pywire.compiler.directives.base import DirectiveParser


class PathDirectiveParser(DirectiveParser):
    """Parses !path directives."""

    PATTERN = re.compile(r"^!path\s+(.+)$", re.DOTALL)

    def can_parse(self, line: str) -> bool:
        """Check if line starts with !path."""
        return line.strip().startswith("!path")

    def parse(self, line: str, line_num: int, col_num: int) -> Optional[PathDirective]:
        """Parse !path { 'name': '/route' } directive."""
        match = self.PATTERN.match(line.strip())
        if not match:
            return None

        routes_str = match.group(1).strip()
        if not routes_str:
            return None

        try:
            # Parse python expression
            expr_ast = ast.parse(routes_str, mode="eval")

            # Case 1: Dictionary !path {'main': '/'}
            if isinstance(expr_ast.body, ast.Dict):
                routes: Dict[str, str] = {}
                for key_node, value_node in zip(expr_ast.body.keys, expr_ast.body.values):
                    if (
                        not isinstance(key_node, ast.Constant)
                        or not isinstance(key_node.value, str)
                        or not isinstance(value_node, ast.Constant)
                        or not isinstance(value_node.value, str)
                    ):
                        return None
                    routes[key_node.value] = value_node.value

                return PathDirective(
                    name="path",
                    routes=routes,
                    is_simple_string=False,
                    line=line_num,
                    column=col_num,
                )

            # Case 2: String !path '/test'
            elif isinstance(expr_ast.body, ast.Constant) and isinstance(expr_ast.body.value, str):
                return PathDirective(
                    name="path",
                    routes={"main": expr_ast.body.value},
                    is_simple_string=True,
                    line=line_num,
                    column=col_num,
                )

            return None
        except (SyntaxError, ValueError, AttributeError):
            return None
