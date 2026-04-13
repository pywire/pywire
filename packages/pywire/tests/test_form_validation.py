"""---
Tests for form validation features."""

import sys
import unittest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

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
        cleaned_data, errors = validator.validate_form(
            data, schema, state_getter=lambda x: None
        )
        self.assertIn("username", errors)
        self.assertIn("email", errors)

        # Valid data
        data = {"username": "john", "email": "john@example.com"}
        cleaned_data, errors = validator.validate_form(
            data, schema, state_getter=lambda x: None
        )
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


class TestPydanticCustomValidators(unittest.TestCase):
    """Test that custom Pydantic validators produce correct FieldErrors."""

    def test_field_validator_error_maps_to_pydantic_source(self) -> None:
        """@field_validator errors should have source='pydantic'."""
        from pydantic import BaseModel, field_validator
        from pywire.runtime.pydantic_integration import validate_with_model

        class StrictUser(BaseModel):
            username: str

            @field_validator("username")
            @classmethod
            def no_spaces(cls, v: str) -> str:
                if " " in v:
                    raise ValueError("No spaces allowed")
                return v

        instance, errors = validate_with_model({"username": "has space"}, StrictUser)
        self.assertIsNone(instance)
        self.assertIn("username", errors)
        self.assertEqual(errors["username"].source, "pydantic")
        self.assertIn("No spaces allowed", errors["username"].message)

    def test_field_validator_success(self) -> None:
        """Valid data should pass custom @field_validator."""
        from pydantic import BaseModel, field_validator
        from pywire.runtime.pydantic_integration import validate_with_model

        class StrictUser(BaseModel):
            username: str

            @field_validator("username")
            @classmethod
            def no_spaces(cls, v: str) -> str:
                if " " in v:
                    raise ValueError("No spaces allowed")
                return v

        instance, errors = validate_with_model({"username": "validuser"}, StrictUser)
        self.assertIsNotNone(instance)
        self.assertEqual(errors, {})
        self.assertEqual(instance.username, "validuser")

    def test_nested_model_error_dot_notation(self) -> None:
        """Nested model errors should produce dot-notation field names."""
        from pydantic import BaseModel
        from pywire.runtime.pydantic_integration import validate_with_model
        from pywire.runtime.form_errors import build_error_namespace

        class Inner(BaseModel):
            city: str

        class Outer(BaseModel):
            name: str
            address: Inner

        # Missing city in nested model
        instance, errors = validate_with_model(
            {"name": "Alice", "address.street": "Main"}, Outer
        )
        self.assertIsNone(instance)
        # Should have a dot-notation key like "address.city"
        nested_keys = [k for k in errors if k.startswith("address.")]
        self.assertTrue(
            len(nested_keys) > 0,
            f"Expected nested error keys, got: {list(errors.keys())}",
        )

        # Verify ErrorNamespace dot access works
        ns = build_error_namespace(errors)
        self.assertTrue(ns.address)
        # At least one nested field should have an error
        has_nested = bool(ns.address.city)
        self.assertTrue(has_nested, "Expected address.city error in namespace")

    def test_nested_model_custom_validator_error(self) -> None:
        """Custom validator on nested model should produce dot-notation error."""
        from pydantic import BaseModel, field_validator
        from pywire.runtime.pydantic_integration import validate_with_model
        from pywire.runtime.form_errors import build_error_namespace

        class Addr(BaseModel):
            city: str

            @field_validator("city")
            @classmethod
            def must_be_upper(cls, v: str) -> str:
                if v != v.upper():
                    raise ValueError("City must be uppercase")
                return v

        class Person(BaseModel):
            name: str
            address: Addr

        instance, errors = validate_with_model(
            {"name": "Bob", "address.city": "nyc"}, Person
        )
        self.assertIsNone(instance)
        self.assertIn("address.city", errors)
        self.assertEqual(errors["address.city"].source, "pydantic")
        self.assertIn("uppercase", errors["address.city"].message.lower())

        # Verify ErrorNamespace dot access
        ns = build_error_namespace(errors)
        self.assertTrue(ns.address.city)
        self.assertEqual(ns.address.city.source, "pydantic")


if __name__ == "__main__":
    unittest.main()
