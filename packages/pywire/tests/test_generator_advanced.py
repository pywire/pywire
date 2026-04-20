import ast
import unittest

from pywire.compiler.ast_nodes import ParsedPyWire
from pywire.compiler.codegen.generator import CodeGenerator


class TestGeneratorAdvanced(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = CodeGenerator()

    def test_generate_spa_metadata(self) -> None:
        from pywire.compiler.ast_nodes import PathDirective

        # Multi-path page enables SPA
        path = PathDirective(
            name="path", routes={"a": "/a", "b": "/b"}, line=1, column=0
        )
        parsed = ParsedPyWire(
            template=[],
            directives=[path],
            python_code="",
            python_ast=ast.parse(""),
            file_path="p.wire",
        )

        stmts = self.generator._generate_spa_metadata(parsed)
        # __spa_enabled__ = True
        self.assertTrue(
            any(
                isinstance(s, ast.Assign)
                and isinstance(s.targets[0], ast.Name)
                and s.targets[0].id == "__spa_enabled__"
                and isinstance(s.value, ast.Constant)
                and s.value.value is True
                for s in stmts
            )
        )
        # __sibling_paths__ = ['/a', '/b']
        self.assertTrue(
            any(
                isinstance(s, ast.Assign)
                and isinstance(s.targets[0], ast.Name)
                and s.targets[0].id == "__sibling_paths__"
                and isinstance(s.value, ast.List)
                and len(s.value.elts) == 2
                for s in stmts
            )
        )

    def test_generate_init_method(self) -> None:
        parsed = ParsedPyWire(
            template=[], python_code="", python_ast=ast.parse(""), file_path="test.wire"
        )
        init_func = self.generator._generate_init_method(parsed)

        self.assertEqual(init_func.name, "__init__")
        # Should call super().__init__ (no more _init_slots call — slot
        # runtime retired in Phase 9).
        self.assertTrue(
            any(
                isinstance(n, ast.Expr)
                and isinstance(n.value, ast.Call)
                and isinstance(n.value.func, ast.Attribute)
                and n.value.func.attr == "__init__"
                for n in init_func.body
            )
        )


if __name__ == "__main__":
    unittest.main()
