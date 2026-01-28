import ast
import unittest

from pywire.compiler.ast_nodes import LayoutDirective, ParsedPyWire, TemplateNode
from pywire.compiler.codegen.generator import CodeGenerator


class TestGeneratorAdvanced(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = CodeGenerator()

    def test_generate_layout_mode(self) -> None:
        # Page with layout inheriting slots
        layout = LayoutDirective(name="layout", layout_path="base.pywire", line=1, column=0)
        parsed = ParsedPyWire(
            template=[TemplateNode(tag="div", children=[], attributes={}, line=1, column=0)],
            directives=[layout],
            python_code="",
            python_ast=ast.parse(""),
            file_path="page.pywire",
        )

        module = self.generator.generate(parsed)
        class_def = next(n for n in module.body if isinstance(n, ast.ClassDef))

        # Should have _init_slots calling super()
        init_slots = next(
            n for n in class_def.body if isinstance(n, ast.FunctionDef) and n.name == "_init_slots"
        )
        self.assertIsInstance(init_slots.body[0], ast.If)  # hasatrr(super(), ...)

        # Should have a parent layout ID hashed
        # hashlib.md5("base.pywire".encode()).hexdigest()

        # Note: path is resolved relative to cwd if not absolute, let's just check
        # it contains a string constant
        self.assertTrue(
            any(isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) for n in init_slots.body)
        )

    def test_generate_spa_metadata(self) -> None:
        from pywire.compiler.ast_nodes import PathDirective

        # Multi-path page enables SPA
        path = PathDirective(name="path", routes={"a": "/a", "b": "/b"}, line=1, column=0)
        parsed = ParsedPyWire(
            template=[],
            directives=[path],
            python_code="",
            python_ast=ast.parse(""),
            file_path="p.pywire",
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
            template=[], python_code="", python_ast=ast.parse(""), file_path="test.pywire"
        )
        init_func = self.generator._generate_init_method(parsed)

        self.assertEqual(init_func.name, "__init__")
        # Should call super().__init__ and self._init_slots()
        self.assertTrue(
            any(
                isinstance(n, ast.Expr)
                and isinstance(n.value, ast.Call)
                and isinstance(n.value.func, ast.Attribute)
                and n.value.func.attr == "__init__"
                for n in init_func.body
            )
        )
        self.assertTrue(
            any(
                isinstance(n, ast.Expr)
                and isinstance(n.value, ast.Call)
                and isinstance(n.value.func, ast.Attribute)
                and n.value.func.attr == "_init_slots"
                for n in init_func.body
            )
        )


if __name__ == "__main__":
    unittest.main()
