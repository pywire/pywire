import ast
import unittest
from typing import cast

from textwrap import dedent

from pywire.compiler.ast_nodes import (
    ParsedPyWire,
    PathDirective,
    TemplateNode,
)
from pywire.compiler.codegen.generator import CodeGenerator
from pywire.compiler.parser import PyWireParser


class TestCodeGenerator(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = CodeGenerator()

    def test_extract_user_imports(self) -> None:
        code = "import os\nfrom math import sqrt"
        tree = ast.parse(code)
        imports = self.generator._extract_user_imports(tree)
        self.assertEqual(len(imports), 2)
        self.assertIsInstance(imports[0], ast.Import)
        self.assertIsInstance(imports[1], ast.ImportFrom)

    def test_extract_user_classes(self) -> None:
        code = "class MyModel:\n    pass\n\ndef my_func():\n    pass"
        tree = ast.parse(code)
        classes = self.generator._extract_user_classes(tree)
        self.assertEqual(len(classes), 1)
        self.assertEqual(cast(ast.ClassDef, classes[0]).name, "MyModel")

    def test_collect_global_names(self) -> None:
        code = "x = 10\ndef func(): pass\nasync def afunc(): pass"
        tree = ast.parse(code)
        methods, variables, async_methods = self.generator._collect_global_names(tree)
        self.assertIn("func", methods)
        self.assertIn("afunc", methods)
        self.assertIn("afunc", async_methods)
        self.assertIn("x", variables)
        self.assertIn("request", variables)  # Default variable

    def test_generate_basic_module(self) -> None:
        parsed = ParsedPyWire(
            template=[
                TemplateNode(tag="div", children=[], attributes={}, line=1, column=0)
            ],
            python_code="name = 'World'",
            python_ast=ast.parse("name = 'World'"),
            file_path="test.wire",
        )
        module = self.generator.generate(parsed)
        self.assertIsInstance(module, ast.Module)

        # Check for class definition
        class_defs = [n for n in module.body if isinstance(n, ast.ClassDef)]
        self.assertEqual(len(class_defs), 1)
        self.assertEqual(class_defs[0].name, "TestPage")

    def test_transform_inline_code_argument_lifting(self) -> None:
        # Test that whole argument expressions are lifted (not just unbound names)
        code = "update_user(user_id, 'new_name')"
        body, args = self.generator._transform_inline_code(
            code, known_methods={"update_user"}
        )

        self.assertEqual(len(args), 2)
        self.assertEqual(args[0], "user_id")
        self.assertEqual(args[1], "'new_name'")

        # Verify the call was transformed to use arg0, arg1
        expr = cast(ast.Expr, body[0])
        call = cast(ast.Call, expr.value)
        self.assertIsInstance(call.args[0], ast.Name)
        self.assertEqual(cast(ast.Name, call.args[0]).id, "arg0")
        self.assertIsInstance(call.args[1], ast.Name)
        self.assertEqual(cast(ast.Name, call.args[1]).id, "arg1")

    def test_extract_import_names(self) -> None:
        code = "import os as my_os\nfrom math import sqrt as my_sqrt"
        tree = ast.parse(code)
        names = self.generator._extract_import_names(tree)
        self.assertIn("my_os", names)
        self.assertIn("my_sqrt", names)
        self.assertIn("json", names)

    def test_generate_spa_script_injection(self) -> None:
        # Multi-path directive triggers SPA injection
        parsed = ParsedPyWire(
            template=[
                TemplateNode(tag="div", children=[], attributes={}, line=1, column=0)
            ],
            directives=[
                PathDirective(
                    name="path",
                    line=1,
                    column=0,
                    routes={"GET": "/a", "POST": "/b"},
                    is_simple_string=False,
                )
            ],
            file_path="test.wire",
        )
        module = self.generator.generate(parsed)

        # Find Page Class
        page_class = next(n for n in module.body if isinstance(n, ast.ClassDef))
        # Look for class attributes in the class body
        spa_enabled_assign = next(
            n
            for n in page_class.body
            if isinstance(n, ast.Assign)
            and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id == "__spa_enabled__"
        )
        self.assertTrue(cast(ast.Constant, spa_enabled_assign.value).value)

        sibling_paths_assign = next(
            n
            for n in page_class.body
            if isinstance(n, ast.Assign)
            and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id == "__sibling_paths__"
        )
        paths = [
            cast(ast.Constant, elt).value
            for elt in cast(ast.List, sibling_paths_assign.value).elts
        ]
        self.assertIn("/a", paths)
        self.assertIn("/b", paths)

    def test_props_decorator_compilation(self) -> None:
        source = dedent("""
            ---
            from pywire import props

            @props
            class Props:
                name: str
                count: int = 0
                variant: str = "primary"
            ---
            <div>{name} ({count})</div>
        """)
        parser = PyWireParser()
        parsed = parser.parse(source, "test.wire")
        module_ast = self.generator.generate(parsed)
        code = ast.unparse(module_ast)
        assert (
            "def __init__(self, request, params, query, path=None, url=None, *, name: str, count: int=0, variant: str='primary', **kwargs):"
            in code
        )
        assert "self.name = name" in code
        assert "self.count = count" in code
        assert "self.variant = variant" in code


if __name__ == "__main__":
    unittest.main()
