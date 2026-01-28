import ast
import sys
import unittest
from pathlib import Path
from typing import cast

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pywire.compiler.codegen.generator import CodeGenerator


class TestMethodBinding(unittest.TestCase):
    def test_method_binding_transform(self) -> None:
        """Test that methods get self and globals are transformed."""
        generator = CodeGenerator()

        # Original code:
        # async def increment_count():
        #     global count
        #     count += 1

        code = """
async def increment_count():
    global count
    count += 1
"""
        module = ast.parse(code)

        # Helper to run the private transform method
        # We need to access _transform_user_code which is instance method
        # But we can also test the logic if we extract it or just check the result of a mock parse

        # Actually, let's test _transform_user_code directly
        transformed = generator._transform_user_code(module)

        self.assertEqual(len(transformed), 1)
        func_def = transformed[0]

        # Check type
        self.assertIsInstance(func_def, ast.AsyncFunctionDef)

        # Check args - MUST have self
        func_def = cast(ast.AsyncFunctionDef, transformed[0])
        self.assertEqual(len(func_def.args.args), 1, "Should have 1 argument")
        self.assertEqual(func_def.args.args[0].arg, "self", "Argument should be 'self'")

        # Check body - NO global stmt, access via self.count
        body = func_def.body
        self.assertEqual(len(body), 1, "Should have 1 statement (assignment)")

        # count += 1  ->  self.count += 1
        aug_assign = body[0]
        self.assertIsInstance(aug_assign, ast.AugAssign)

        # Target should be self.count
        target = cast(ast.AugAssign, aug_assign).target
        self.assertIsInstance(target, ast.Attribute)
        self.assertEqual(cast(ast.Attribute, target).attr, "count")
        self.assertIsInstance(cast(ast.Attribute, target).value, ast.Name)
        self.assertEqual(cast(ast.Name, cast(ast.Attribute, target).value).id, "self")

    def test_normal_function_transform(self) -> None:
        """Test synchronous functions too."""
        generator = CodeGenerator()
        code = """
def update():
    return True
"""
        module = ast.parse(code)
        transformed = generator._transform_user_code(module)

        func_def = cast(ast.FunctionDef, transformed[0])
        self.assertEqual(func_def.args.args[0].arg, "self")


if __name__ == "__main__":
    unittest.main()
