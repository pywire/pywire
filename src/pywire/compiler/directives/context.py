import ast
from typing import Optional

from pywire.compiler.ast_nodes import Directive, InjectDirective, ProvideDirective
from pywire.compiler.directives.base import DirectiveParser


class ContextDirectiveParser(DirectiveParser):
    """Parses !inject and !provide"""

    def can_parse(self, line: str) -> bool:
        return line.startswith("!inject") or line.startswith("!provide")

    def parse(self, line: str, line_num: int, col_num: int) -> Optional[Directive]:
        is_inject = line.startswith("!inject")
        directive_name = "!inject" if is_inject else "!provide"

        content = line[len(directive_name) :].strip()

        # Wrapped in dict braces?
        if not content.startswith("{") or not content.endswith("}"):
            # Maybe they omitted braces? Let's assume strict syntax for now as per design doc
            # !inject { ... }
            return None

        try:
            # Parse as a dictionary expression
            # code: _ = { ... }
            dummy_code = f"_ = {content}"
            mod = ast.parse(dummy_code)
            assign = mod.body[0]
            if not isinstance(assign, ast.Assign) or not isinstance(assign.value, ast.Dict):
                return None

            dict_node = assign.value

            mapping = {}

            for key_node, value_node in zip(dict_node.keys, dict_node.values):
                if is_inject:
                    # !inject { local_var: 'GLOBAL_KEY' }
                    # key should be the local variable name (Name node or Constant string)
                    # value should be the context key (Constant string)

                    local_var = None
                    if isinstance(key_node, ast.Name):
                        local_var = key_node.id
                    elif isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                        local_var = key_node.value

                    global_key = None
                    if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
                        global_key = value_node.value

                    if local_var and global_key:
                        mapping[local_var] = global_key

                else:
                    # !provide { 'GLOBAL_KEY': local_expr }
                    # key must be string
                    # value is expression to be evaluated at runtime

                    global_key = None
                    if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                        global_key = key_node.value

                    # Convert value node back to source string to be put in generated code
                    val_expr = ""
                    if hasattr(ast, "unparse"):
                        val_expr = ast.unparse(value_node)

                    if global_key:
                        mapping[global_key] = val_expr

            if is_inject:
                return InjectDirective(
                    line=line_num, column=col_num, name="!inject", mapping=mapping
                )
            else:
                return ProvideDirective(
                    line=line_num, column=col_num, name="!provide", mapping=mapping
                )

        except Exception:
            return None
