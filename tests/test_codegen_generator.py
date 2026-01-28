import ast
import unittest
from typing import cast

from pywire.compiler.ast_nodes import (
    EventAttribute,
    FieldValidationRules,
    FormValidationSchema,
    ParsedPyWire,
    PathDirective,
    TemplateNode,
)
from pywire.compiler.codegen.generator import CodeGenerator


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
            template=[TemplateNode(tag="div", children=[], attributes={}, line=1, column=0)],
            python_code="name = 'World'",
            python_ast=ast.parse("name = 'World'"),
            file_path="test.pywire",
        )
        module = self.generator.generate(parsed)
        self.assertIsInstance(module, ast.Module)

        # Check for class definition
        class_defs = [n for n in module.body if isinstance(n, ast.ClassDef)]
        self.assertEqual(len(class_defs), 1)
        self.assertEqual(class_defs[0].name, "TestPage")

    def test_transform_inline_code_argument_lifting(self) -> None:
        # Test that unbound variables in arguments are lifted to parameters
        code = "update_user(user_id, 'new_name')"
        # user_id is unbound
        body, args = self.generator._transform_inline_code(code, known_methods={"update_user"})

        self.assertEqual(len(args), 1)
        self.assertEqual(args[0], "user_id")

        # Verify the call was transformed to use arg0
        expr = cast(ast.Expr, body[0])
        call = cast(ast.Call, expr.value)
        self.assertIsInstance(call.args[0], ast.Name)
        self.assertEqual(cast(ast.Name, call.args[0]).id, "arg0")

    def test_generate_form_validation(self) -> None:
        schema = FormValidationSchema(
            fields={"email": FieldValidationRules(name="email", required=True, input_type="email")}
        )
        node = TemplateNode(tag="form", line=1, column=0)
        node.special_attributes = [
            EventAttribute(
                name="@submit",
                value="save",
                event_type="submit",
                handler_name="save",
                validation_schema=schema,
                line=1,
                column=0,
            )
        ]
        parsed = ParsedPyWire(template=[node])

        methods = self.generator._generate_form_validation_methods(parsed, set())
        # Should have schema assignment and wrapper method
        self.assertEqual(len(methods), 2)
        self.assertIsInstance(methods[0], ast.Assign)
        self.assertIsInstance(methods[1], ast.AsyncFunctionDef)
        self.assertTrue(cast(ast.AsyncFunctionDef, methods[1]).name.startswith("_form_submit_"))

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
            template=[TemplateNode(tag="div", children=[], attributes={}, line=1, column=0)],
            directives=[
                PathDirective(
                    name="path",
                    line=1,
                    column=0,
                    routes={"/a": "a", "/b": "b"},
                    is_simple_string=False,
                )
            ],
            file_path="test.pywire",
        )
        module = self.generator.generate(parsed)

        # Find Page Class
        page_class = next(n for n in module.body if isinstance(n, ast.ClassDef))
        # Find _render_template method
        render_func = next(
            n
            for n in page_class.body
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_render_template"
        )

        # DEBUG
        # print(ast.dump(render_func))

        # Look for script tag injection in the body
        script_appends = []
        for n in render_func.body:
            # The injection might be nested in an If statement (spa_check)
            nodes_to_check = [n]
            if isinstance(n, ast.If):
                nodes_to_check.extend(n.body)

            for node in nodes_to_check:
                if (
                    isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Call)
                    and node.value.args
                ):
                    arg0 = node.value.args[0]
                    if (
                        isinstance(arg0, ast.Constant)
                        and isinstance(arg0.value, str)
                        and "<script" in arg0.value
                    ):
                        script_appends.append(node)
                    elif isinstance(arg0, ast.JoinedStr):
                        # Check first constant part of JoinedStr
                        if (
                            arg0.values
                            and isinstance(arg0.values[0], ast.Constant)
                            and "<script" in str(cast(ast.Constant, arg0.values[0]).value)
                        ):
                            script_appends.append(node)

        # Should have SPA meta script (constant parts) and client library script (JoinedStr)
        self.assertTrue(len(script_appends) >= 2)


if __name__ == "__main__":
    unittest.main()
