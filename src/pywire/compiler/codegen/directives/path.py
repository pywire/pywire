"""Path directive code generator."""

import ast
from typing import List

from pywire.compiler.ast_nodes import Directive, PathDirective
from pywire.compiler.codegen.directives.base import DirectiveCodegen


class PathDirectiveCodegen(DirectiveCodegen):
    """Generates routing metadata from !path."""

    def generate(self, directive: Directive) -> List[ast.stmt]:
        """Generate route metadata assignments."""
        assert isinstance(directive, PathDirective)
        statements: List[ast.stmt] = []

        # Generate __routes__ dict with all route names
        routes_dict = {}
        for name, pattern in directive.routes.items():
            routes_dict[name] = pattern

        routes_ast = ast.Dict(
            keys=[ast.Constant(value=k) for k in routes_dict.keys()],
            values=[ast.Constant(value=v) for v in routes_dict.values()],
        )

        statements.append(
            ast.Assign(targets=[ast.Name(id="__routes__", ctx=ast.Store())], value=routes_ast)
        )

        # Generate __path_mode__
        mode = "string" if directive.is_simple_string else "dict"
        statements.append(
            ast.Assign(
                targets=[ast.Name(id="__path_mode__", ctx=ast.Store())],
                value=ast.Constant(value=mode),
            )
        )

        # Generate __route__ with first route pattern (for backward compatibility)
        if routes_dict:
            first_pattern = list(routes_dict.values())[0]
            statements.append(
                ast.Assign(
                    targets=[ast.Name(id="__route__", ctx=ast.Store())],
                    value=ast.Constant(value=first_pattern),
                )
            )

        return statements
