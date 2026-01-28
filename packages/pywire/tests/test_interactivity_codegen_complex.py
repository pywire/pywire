import ast
import unittest

from pywire.compiler.ast_nodes import EventAttribute
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
        content = f"{template}\n---\n{python_code}"
        parsed = self.parser.parse(content)

        # Generate code
        module_ast = self.generator.generate(parsed)
        code = ast.unparse(module_ast)

        # Verify handler method generation
        # Since it's an async method in the python block, it should be awaited
        self.assertIn("async def _handler_0(self, arg0):", code)
        self.assertIn("await self.delete_item(arg0, 'confirmed')", code)

        # Verify render template call
        # It should pass the arguments to the generator
        self.assertIn("data-arg-0", code)
        self.assertNotIn("data-arg-1", code)  # 'confirmed' is a literal, not lifted

    def test_multiple_handlers_complex(self) -> None:
        """Verify behavior with multiple handlers having arguments and modifiers."""
        template = "<button @click.stop={foo(id1)} @click.prevent={bar(id2)}>Click</button>"
        parsed = self.parser.parse(template)

        module_ast = self.generator.generate(parsed)
        code = ast.unparse(module_ast)

        # Verify JSON contains args placeholders (since they are lifted)
        # AST codegen produces direct list assignment: _h['args'] = [self.id1]
        self.assertIn("_h['args'] = [self.id1]", code)
        self.assertIn("_h['args'] = [self.id2]", code)
        # Verify modifiers are collected (order is unstable because of set())
        modifiers_line = [
            line for line in code.split("\n") if "attrs['data-modifiers-click'] =" in line
        ][0]
        self.assertIn("stop", modifiers_line)
        self.assertIn("prevent", modifiers_line)

    def test_form_validation_wrapper(self) -> None:
        """Test that @submit on a form with validation schema generates a wrapper."""
        # This requires more setup (mocking a validation schema in the AST)
        # For now, let's verify if the generator handles EventAttribute with validation_schema
        from pywire.compiler.ast_nodes import FieldValidationRules, FormValidationSchema

        template = '<form @submit={save}><input name="user"></form>'
        parsed = self.parser.parse(template)

        # Manually inject a validation schema for the test
        for attr in parsed.template[0].special_attributes:
            if isinstance(attr, EventAttribute) and attr.event_type == "submit":
                attr.validation_schema = FormValidationSchema(
                    fields={"user": FieldValidationRules(name="user", required=True, minlength=3)}
                )

        module_ast = self.generator.generate(parsed)
        code = ast.unparse(module_ast)

        # Verify wrapper generation
        self.assertIn("async def _form_submit_0(self, **kwargs):", code)
        self.assertIn("form_validator.validate_form", code)
        self.assertIn("self._form_schema_0.fields", code)
        self.assertIn("await self.save(cleaned_data)", code)


if __name__ == "__main__":
    unittest.main()
