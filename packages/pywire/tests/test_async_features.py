import ast
import sys
import unittest
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from pywire.compiler.ast_nodes import EventAttribute, ParsedPyWire, TemplateNode
from pywire.compiler.codegen.generator import CodeGenerator


class TestAsyncFeatures(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = CodeGenerator()

    def compile_and_get_handlers(self, template_node: Any, python_code: str = "") -> Any:
        parsed = ParsedPyWire(
            template=[template_node],
            python_code=python_code,
            python_ast=ast.parse(python_code) if python_code else None,
            file_path="test_async.pywire",
        )

        module_ast = self.generator.generate(parsed)
        ast.fix_missing_locations(module_ast)

        handlers = {}
        for node in module_ast.body:
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.AsyncFunctionDef) and item.name.startswith("_handler_"):
                        handlers[item.name] = item
        return handlers, parsed

    def test_implicit_async_await(self) -> None:
        # Python code with async method
        py_code = """
async def my_async_task(self):
    pass
"""

        # <button @click={my_async_task()}>
        click_attr = EventAttribute(
            line=1,
            column=1,
            name="@click",
            value="my_async_task()",
            event_type="click",
            handler_name="my_async_task()",
        )

        button = TemplateNode(line=1, column=1, tag="button", special_attributes=[click_attr])

        handlers, parsed = self.compile_and_get_handlers(button, py_code)

        # Verify wrapper created
        self.assertEqual(len(handlers), 1)
        handler = list(handlers.values())[0]

        # Verify body contains await
        source = ast.unparse(handler)
        self.assertIn("await self.my_async_task()", source)
        print("\nTest Implicit Async Await Source:\n", source)


if __name__ == "__main__":
    unittest.main()
