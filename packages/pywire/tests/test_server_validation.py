import sys
import unittest
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pywire.runtime.validation import FieldRules, FormValidator


class TestServerValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = FormValidator()

    def test_numeric_min_max(self) -> None:
        """Test numeric min/max constraints."""
        rules = FieldRules(input_type="number", min_value="5", max_value="10")

        # Valid
        self.assertIsNone(self.validator.validate_field("age", "5", rules))
        self.assertIsNone(self.validator.validate_field("age", "10", rules))
        self.assertIsNone(self.validator.validate_field("age", "7", rules))

        # Invalid
        self.assertIsNotNone(self.validator.validate_field("age", "4", rules))
        self.assertIsNotNone(self.validator.validate_field("age", "11", rules))

        # Invalid type (but validate_field takes string usually)
        # The form validator converts first.
        # Let's test _validate_number directly or via validate_field which calls it.
        # validate_field(..., "abc", ...) -> valid number check
        self.assertIsNotNone(self.validator.validate_field("age", "abc", rules))

    def test_numeric_step(self) -> None:
        """Test numeric step validation."""
        rules = FieldRules(input_type="number", step="2", min_value="0")

        # Valid
        self.assertIsNone(self.validator.validate_field("count", "0", rules))
        self.assertIsNone(self.validator.validate_field("count", "2", rules))
        self.assertIsNone(self.validator.validate_field("count", "10", rules))

        # Invalid
        self.assertIsNotNone(self.validator.validate_field("count", "1", rules))
        self.assertIsNotNone(self.validator.validate_field("count", "3", rules))

    def test_string_length(self) -> None:
        """Test string length validation."""
        rules = FieldRules(minlength=3, maxlength=5)

        # Valid
        self.assertIsNone(self.validator.validate_field("user", "abc", rules))
        self.assertIsNone(self.validator.validate_field("user", "abcde", rules))

        # Invalid
        self.assertIsNotNone(self.validator.validate_field("user", "ab", rules))
        self.assertIsNotNone(self.validator.validate_field("user", "abcdef", rules))

    def test_pattern(self) -> None:
        """Test regex pattern validation."""
        rules = FieldRules(pattern=r"^\d{3}$")

        # Valid
        self.assertIsNone(self.validator.validate_field("code", "123", rules))

        # Invalid
        self.assertIsNotNone(self.validator.validate_field("code", "12a", rules))
        self.assertIsNotNone(self.validator.validate_field("code", "1234", rules))

    def test_type_email(self) -> None:
        """Test email validation."""
        rules = FieldRules(input_type="email")

        self.assertIsNone(self.validator.validate_field("email", "test@test.com", rules))
        self.assertIsNotNone(self.validator.validate_field("email", "test", rules))
        self.assertIsNotNone(
            self.validator.validate_field("email", "test@com", rules)
        )  # naive regex?

    def test_required(self) -> None:
        """Test required validation."""
        rules = FieldRules(required=True)

        self.assertIsNotNone(self.validator.validate_field("req", "", rules))
        self.assertIsNotNone(self.validator.validate_field("req", None, rules))
        self.assertIsNone(self.validator.validate_field("req", "val", rules))

        # Not required (default)
        rules_opt = FieldRules(required=False)
        self.assertIsNone(self.validator.validate_field("opt", "", rules_opt))
        self.assertIsNone(self.validator.validate_field("opt", None, rules_opt))

    async def test_validate_server_error(self) -> None:
        """Test validate_form handles type conversion and returns strictly typed data."""
        schema = {
            "age": FieldRules(input_type="number", min_value="18"),
            "active": FieldRules(input_type="checkbox"),
            "email": FieldRules(input_type="email"),
        }

        # Form data matches what comes from starlette/HTML form (strings)
        data = {"age": "20", "active": "on", "email": "test@example.com"}

        cleaned, errors = self.validator.validate_form(data, schema, state_getter=lambda x: None)
        self.assertEqual(errors, {})
        self.assertIsInstance(cleaned["age"], (int, float))
        self.assertEqual(cleaned["age"], 20)
        self.assertIsInstance(cleaned["active"], bool)
        self.assertTrue(cleaned["active"])
        self.assertEqual(cleaned["email"], "test@example.com")

    def test_dynamic_validation(self) -> None:
        """Test dynamic expression validation."""
        # Simulating a state getter
        state = {"min_age": 21, "is_admin": True}

        def get_state(expr: str) -> Any:
            return eval(expr, {}, state)

        rules = FieldRules(
            input_type="number",
            min_expr="min_age",
            required_expr="not is_admin",  # Should evaluate to False
        )

        # Case 1: Value meeting dynamic min
        self.assertIsNone(self.validator.validate_field("val", "22", rules, state_getter=get_state))

        # Case 2: Value failing dynamic min
        self.assertIsNotNone(
            self.validator.validate_field("val", "20", rules, state_getter=get_state)
        )

        # Case 3: Required check
        # admin is True, so required is False. Empty should pass.
        self.assertIsNone(self.validator.validate_field("val", "", rules, state_getter=get_state))

        # Change state
        state["is_admin"] = False
        # Now required is True. Empty should fail.
        self.assertIsNotNone(
            self.validator.validate_field("val", "", rules, state_getter=get_state)
        )


if __name__ == "__main__":
    unittest.main()
