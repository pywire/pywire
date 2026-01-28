import ast
from typing import List, Optional, Tuple

from pywire.compiler.ast_nodes import Directive, PropsDirective
from pywire.compiler.directives.base import DirectiveParser


class PropsDirectiveParser(DirectiveParser):
    """Parses !props(name: type, arg=default)"""

    def can_parse(self, line: str) -> bool:
        return line.startswith("!props")

    def parse(self, line: str, line_num: int, col_num: int) -> Optional[Directive]:
        # Format: !props(arg: type, arg2=default)

        # 1. Extract content inside parentheses
        # Note: 'line' might be multiline string passed from parser.
        # We assume the parser handles accumulation until matching parens if needed.
        # Or we rely on the fact that directives are usually single line or we need to handle it.
        # The main parser accumulates if braces/brackets match, but what about parens?
        # The main parser logic: "Count open braces/brackets". It does NOT count parens currently.
        # We might need to update the main parser to also count parens for !props?
        # For now, let's assume it's passed correctly or single line.

        # Strip '!props'
        content = line[len("!props") :].strip()
        if not content.startswith("(") or not content.endswith(")"):
            return None

        # content is "(...)"

        # 2. Use AST parsing by wrapping in a function def
        # This handles complex types, strings with commas, etc.
        dummy_code = f"def _p{content}: pass"

        try:
            mod = ast.parse(dummy_code)
            func_def = mod.body[0]
            if not isinstance(func_def, ast.FunctionDef):
                return None

            args = func_def.args

            parsed_args: List[Tuple[str, str, Optional[str]]] = []

            # Helper to get source segment if possible, or unparse
            def unparse_node(node: ast.AST) -> str:
                if hasattr(ast, "unparse"):
                    source = ast.unparse(node)
                    # ast.unparse might return something slightly different formatted,
                    # which is fine for type strings
                    return source
                return ""  # Fallback for older python if needed, but we likely preserve 3.9+

            # Process args (normal arguments)
            # defaults are at the end of the list.
            # e.g. args.args = [a, b], args.defaults = [def_b] -> a has no default, b has def_b

            num_args = len(args.args)
            num_defaults = len(args.defaults)
            offset = num_args - num_defaults

            for i, arg in enumerate(args.args):
                name = arg.arg
                type_hint = "Any"
                if arg.annotation:
                    type_hint = unparse_node(arg.annotation)

                default_val = None
                if i >= offset:
                    default_idx = i - offset
                    default_val = unparse_node(args.defaults[default_idx])

                parsed_args.append((name, type_hint, default_val))

            # TODO: Handle kwonlyargs if we want to enforce keyword only props?
            # For now simple args.

            return PropsDirective(line=line_num, column=col_num, name="!props", args=parsed_args)

        except SyntaxError:
            # Invalid python syntax in props
            return None
        except Exception:
            return None
