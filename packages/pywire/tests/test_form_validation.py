"""Tests for form validation features."""

import ast
import sys
import unittest
from pathlib import Path
from typing import Any, cast

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pywire.compiler.codegen.generator import CodeGenerator
from pywire.compiler.parser import PyWireParser
from pywire.runtime.validation import FieldRules, FormValidator


class TestFormValidation(unittest.TestCase):
    """Test form validation module."""

    def test_required_validation(self) -> None:
        """Test required field validation."""
        validator = FormValidator()
        rules = FieldRules(required=True)

        # Empty string should fail
        error = validator.validate_field("username", "", rules)
        self.assertIsNotNone(error)

        # Valid value should pass
        error = validator.validate_field("username", "john", rules)
        self.assertIsNone(error)

    def test_pattern_validation(self) -> None:
        """Test pattern validation."""
        validator = FormValidator()
        rules = FieldRules(pattern=r"^[A-Z]{3}[0-9]{3}$")

        # Invalid pattern should fail
        error = validator.validate_field("code", "abc123", rules)
        self.assertIsNotNone(error)

        # Valid pattern should pass
        error = validator.validate_field("code", "ABC123", rules)
        self.assertIsNone(error)

    def test_length_validation(self) -> None:
        """Test minlength and maxlength validation."""
        validator = FormValidator()
        rules = FieldRules(minlength=3, maxlength=10)

        # Too short
        error = validator.validate_field("name", "ab", rules)
        self.assertIsNotNone(error)

        # Too long
        error = validator.validate_field("name", "a" * 11, rules)
        self.assertIsNotNone(error)

        # Valid
        error = validator.validate_field("name", "hello", rules)
        self.assertIsNone(error)

    def test_email_validation(self) -> None:
        """Test email type validation."""
        validator = FormValidator()
        rules = FieldRules(input_type="email")

        # Invalid email
        error = validator.validate_field("email", "notanemail", rules)
        self.assertIsNotNone(error)

        # Valid email
        error = validator.validate_field("email", "test@example.com", rules)
        self.assertIsNone(error)

    def test_number_range_validation(self) -> None:
        """Test number range validation."""
        validator = FormValidator()
        rules = FieldRules(input_type="number", min_value="10", max_value="100")

        # Below min
        error = validator.validate_field("age", "5", rules)
        self.assertIsNotNone(error)

        # Above max
        error = validator.validate_field("age", "150", rules)
        self.assertIsNotNone(error)

        # Valid
        error = validator.validate_field("age", "50", rules)
        self.assertIsNone(error)

    def test_form_validation(self) -> None:
        """Test full form validation."""
        validator = FormValidator()
        schema = {
            "username": FieldRules(required=True, minlength=3),
            "email": FieldRules(required=True, input_type="email"),
        }

        # Invalid data
        data = {"username": "ab", "email": "invalid"}
        cleaned_data, errors = validator.validate_form(data, schema, state_getter=lambda x: None)
        self.assertIn("username", errors)
        self.assertIn("email", errors)

        # Valid data
        data = {"username": "john", "email": "john@example.com"}
        cleaned_data, errors = validator.validate_form(data, schema, state_getter=lambda x: None)
        self.assertEqual(errors, {})

    def test_nested_data_parsing(self) -> None:
        """Test parsing of dotted field names."""
        flat_data = {
            "customer.name": "John",
            "customer.email": "john@example.com",
            "shipping.street": "123 Main St",
            "shipping.city": "NYC",
        }

        result = FormValidator.parse_nested_data(flat_data)

        self.assertEqual(result["customer"]["name"], "John")
        self.assertEqual(result["customer"]["email"], "john@example.com")
        self.assertEqual(result["shipping"]["street"], "123 Main St")


class TestFormParsing(unittest.TestCase):
    """Test form parsing and validation schema extraction."""

    def test_form_with_submit_extracts_schema(self) -> None:
        """Test that @submit forms extract validation schema."""
        parser = PyWireParser()

        content = """
<form @submit={handle_form}>
    <input name="username" required minlength="3" maxlength="20">
    <input name="email" type="email" required>
    <input name="age" type="number" min="18" max="100">
    <button type="submit">Submit</button>
</form>

---
async def handle_form(data):
    pass
"""

        parsed = parser.parse(content)

        # Find the form node
        form_node = None
        for node in parsed.template:
            if node.tag == "form":
                form_node = node
                break

        self.assertIsNotNone(form_node, "Form node not found")

        # Find the @submit event
        from pywire.compiler.ast_nodes import EventAttribute, TemplateNode

        submit_attr = None
        for attr in cast(TemplateNode, form_node).special_attributes:
            if isinstance(attr, EventAttribute) and attr.event_type == "submit":
                submit_attr = attr
                break

        self.assertIsNotNone(submit_attr, "@submit attribute not found")
        self.assertIsNotNone(
            cast(Any, submit_attr).validation_schema, "Validation schema not attached"
        )

        # Check schema fields
        schema = cast(Any, submit_attr).validation_schema
        self.assertIn("username", schema.fields)
        self.assertIn("email", schema.fields)
        self.assertIn("age", schema.fields)

        # Check username rules
        username_rules = schema.fields["username"]
        self.assertTrue(username_rules.required)
        self.assertEqual(username_rules.minlength, 3)
        self.assertEqual(username_rules.maxlength, 20)

        # Check email rules
        email_rules = schema.fields["email"]
        self.assertTrue(email_rules.required)
        self.assertEqual(email_rules.input_type, "email")

        # Check age rules
        age_rules = schema.fields["age"]
        self.assertEqual(age_rules.input_type, "number")
        self.assertEqual(age_rules.min_value, "18")
        self.assertEqual(age_rules.max_value, "100")


class TestFormCodegen(unittest.TestCase):
    """Test form validation code generation."""

    def test_form_generates_wrapper(self) -> None:
        """Test that forms with validation generate wrapper handlers."""
        parser = PyWireParser()
        generator = CodeGenerator()

        content = """
<form @submit={handle_form}>
    <input name="username" required minlength="3">
    <button type="submit">Submit</button>
</form>

---
async def handle_form(data):
    pass
"""

        parsed = parser.parse(content)
        module_ast = generator.generate(parsed)

        # Get generated code
        code = ast.unparse(module_ast)

        # Should contain form schema
        self.assertIn("_form_schema_0", code)
        self.assertIn("FieldRules", code)

        # Should contain wrapper handler
        self.assertIn("_form_submit_0", code)
        self.assertIn("form_validator.validate_form", code)

        # Should check errors and early return
        self.assertIn("self.errors", code)


if __name__ == "__main__":
    unittest.main()
