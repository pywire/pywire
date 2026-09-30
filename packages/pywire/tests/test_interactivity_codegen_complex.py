import ast
import unittest

from pywire.compiler.codegen.generator import CodeGenerator
from pywire.compiler.parser import PyWireParser


class TestInteractivityCodegenComplex(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = CodeGenerator()
        self.parser = PyWireParser()

    def test_inline_argument_lifting(self) -> None:
        """Test that @click={delete_item(item.id, 'confirm')} lifts arguments."""
        template = "<button @click={delete_item(item.id, 'confirmed')}>Delete</button>"
        # Mock python code with the handler method
        python_code = "async def delete_item(id, status): pass"
        content = f"---\n{python_code}\n---\n{template}"
        parsed = self.parser.parse(content)

        # Generate code
        module_ast = self.generator.generate(parsed)
        code = ast.unparse(module_ast)

        # Verify handler method generation - whole-arg lifting passes both args
        self.assertIn("async def _handler_0(self, arg0, arg1, *, event=None):", code)
        self.assertIn("await self.delete_item(arg0, arg1)", code)

        # Verify render template - signs the expr results for the handler
        self.assertIn(
            "attrs['data-pw-args-click'] = self._pw_sign_args('_handler_0', "
            "unwrap_wire(self.item.id), unwrap_wire('confirmed'))",
            code,
        )

    def test_multiple_handlers_complex(self) -> None:
        """Verify behavior with multiple handlers having arguments and modifiers."""
        template = (
            "<button @click.stop={foo(id1)} @click.prevent={bar(id2)}>Click</button>"
        )
        # Add python code to define handlers
        python_code = "async def foo(id): pass\nasync def bar(id): pass"
        content = f"---\n{python_code}\n---\n{template}"
        parsed = self.parser.parse(content)

        module_ast = self.generator.generate(parsed)
        code = ast.unparse(module_ast)

        # Each handler's args are signed for that handler
        self.assertIn(
            "_h['args'] = self._pw_sign_args('_handler_0', unwrap_wire(self.id1))",
            code,
        )
        self.assertIn(
            "_h['args'] = self._pw_sign_args('_handler_1', unwrap_wire(self.id2))",
            code,
        )
        # Modifiers are collected in a stable order
        self.assertIn("attrs['data-modifiers-click'] = 'prevent stop'", code)

    def test_loop_click_handler_id_based(self) -> None:
        """Regression: @click={handler(item.get('id',''))} inside $for serializes id expr, not full item."""
        template = """
        <div $for={item in items} $key={item.get('id','')}>
            <button @click={delete_by_id(item.get('id', ''))}>Delete</button>
        </div>
        """
        python_code = "items = []\ndef delete_by_id(rid): pass"
        content = f"---\n{python_code}\n---\n{template}"
        parsed = self.parser.parse(content)

        module_ast = self.generator.generate(parsed)
        code = ast.unparse(module_ast)

        # Handler receives arg0 (the serialized expr result = id string)
        self.assertIn("async def _handler_0(self, arg0, *, event=None):", code)
        self.assertIn("self.delete_by_id(arg0)", code)
        # The signed arg is the item.get('id','') result, not the full item
        self.assertIn(
            "self._pw_sign_args('_handler_0', unwrap_wire(item.get('id', '')))", code
        )
        self.assertNotIn("json.dumps(item)", code)


if __name__ == "__main__":
    unittest.main()
