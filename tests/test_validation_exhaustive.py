import unittest
from typing import cast

from pydantic import BaseModel, Field
from pywire.runtime.pydantic_integration import validate_with_model
from pywire.runtime.validation import FieldRules, form_validator

validate_form = form_validator.validate_form


class SimpleModel(BaseModel):
    name: str = Field(min_length=2)
    email: str = Field(pattern=r"[^@]+@[^@]+")
    age: int = Field(ge=18)


class TestValidationExhaustive(unittest.TestCase):
    def test_validate_form_basic_rules(self) -> None:
        fields = {
            "name": FieldRules(required=True, minlength=2),
            "age": FieldRules(input_type="number", min_value="18"),
            "email": FieldRules(input_type="email", pattern=r"[^@]+@[^@]+"),
        }

        # 1. Valid data
        data = {"name": "Reece", "age": "25", "email": "r@example.com"}
        cleaned, errors = validate_form(data, fields, lambda x: None)
        self.assertEqual(len(errors), 0)
        self.assertEqual(cleaned["name"], "Reece")
        self.assertEqual(cleaned["age"], 25)  # Check type conversion

        # 2. Invalid data
        data = {"name": "R", "age": "17", "email": "invalid"}
        cleaned, errors = validate_form(data, fields, lambda x: None)
        self.assertIn("name", errors)
        self.assertIn("age", errors)
        self.assertIn("email", errors)

    def test_validate_with_model_success(self) -> None:
        data = {"name": "Reece", "email": "r@example.com", "age": 25}
        instance, errors = validate_with_model(data, SimpleModel)
        self.assertEqual(len(errors), 0)
        self.assertIsInstance(instance, SimpleModel)
        self.assertEqual(cast(SimpleModel, instance).name, "Reece")

    def test_validate_with_model_failure(self) -> None:
        data = {"name": "R", "email": "invalid", "age": 10}
        instance, errors = validate_with_model(data, SimpleModel)
        self.assertIsNone(instance)
        self.assertGreater(len(errors), 0)
        self.assertIn("name", errors)
        self.assertIn("email", errors)

    def test_validate_form_conditional(self) -> None:
        # Test get_state for conditional required
        fields = {"is_admin": FieldRules(), "admin_code": FieldRules(required_expr="is_admin")}

        # Mock get_state to simulate self.is_admin
        def get_state(expr: str) -> bool:
            state = {"is_admin": True}
            return state.get(expr, False)

        data = {"is_admin": "on", "admin_code": ""}
        cleaned, errors = validate_form(data, fields, get_state)
        self.assertIn("admin_code", errors)

    def test_validate_date(self) -> None:
        fields = {
            "start_date": FieldRules(
                input_type="date", min_value="2023-01-01", max_value="2023-12-31"
            )
        }

        # 1. Valid
        data = {"start_date": "2023-06-01"}
        cleaned, errors = validate_form(data, fields, lambda x: None)
        self.assertEqual(len(errors), 0)

        # 2. Too early
        data = {"start_date": "2022-12-31"}
        cleaned, errors = validate_form(data, fields, lambda x: None)
        self.assertIn("start_date", errors)

        # 3. Too late
        data = {"start_date": "2024-01-01"}
        cleaned, errors = validate_form(data, fields, lambda x: None)
        self.assertIn("start_date", errors)

        # 4. Invalid format
        data = {"start_date": "not-a-date"}
        cleaned, errors = validate_form(data, fields, lambda x: None)
        self.assertIn("start_date", errors)

    def test_validate_numeric_step(self) -> None:
        fields = {"amount": FieldRules(input_type="number", step="0.5", min_value="1.0")}

        # 1. Valid
        data = {"amount": "1.5"}
        cleaned, errors = validate_form(data, fields, lambda x: None)
        self.assertEqual(len(errors), 0)

        # 2. Invalid step
        data = {"amount": "1.2"}
        cleaned, errors = validate_form(data, fields, lambda x: None)
        self.assertIn("amount", errors)

    def test_parse_nested_data(self) -> None:
        flat_data = {"user.name": "Reece", "user.address.city": "SF", "active": True}
        nested = form_validator.parse_nested_data(flat_data)
        self.assertEqual(nested["user"]["name"], "Reece")
        self.assertEqual(nested["user"]["address"]["city"], "SF")
        self.assertEqual(nested["active"], True)

    def test_convert_checkbox(self) -> None:
        # checkbox 'on' -> True
        self.assertTrue(form_validator._convert_value("on", "checkbox"))
        self.assertTrue(form_validator._convert_value("true", "checkbox"))
        self.assertFalse(form_validator._convert_value("off", "checkbox"))
        self.assertFalse(form_validator._convert_value("", "checkbox"))

    def test_enum_conversion(self) -> None:
        from enum import Enum

        class Color(Enum):
            RED = 1
            BLUE = 2

        self.assertEqual(form_validator.convert_to_type(1, Color), Color.RED)
        self.assertEqual(form_validator.convert_to_type("RED", Color), Color.RED)
        self.assertEqual(form_validator.convert_to_type("blue", Color), Color.BLUE)
        self.assertEqual(form_validator.convert_to_type("invalid", Color), "invalid")

    def test_file_validation_mock(self) -> None:
        from unittest.mock import MagicMock

        from pywire.runtime.files import FileUpload

        fields = {
            "avatar": FieldRules(
                input_type="file", max_size=1024, allowed_types=["image/*", ".pdf"]
            )
        }

        # 1. Valid file
        mock_file = MagicMock(spec=FileUpload)
        mock_file.size = 500
        mock_file.content_type = "image/png"
        mock_file.filename = "test.png"

        error = form_validator.validate_field("avatar", mock_file, fields["avatar"])
        self.assertIsNone(error)

        # 2. Too large
        mock_file.size = 2000
        error = form_validator.validate_field("avatar", mock_file, fields["avatar"])
        self.assertIn("too large", cast(str, error))

        # 3. Wrong type
        mock_file.size = 500
        mock_file.content_type = "text/plain"
        mock_file.filename = "test.txt"
        error = form_validator.validate_field("avatar", mock_file, fields["avatar"])
        self.assertIn("not allowed", cast(str, error))

        # 4. Extension allowed
        mock_file.filename = "document.pdf"
        mock_file.content_type = "application/pdf"
        error = form_validator.validate_field("avatar", mock_file, fields["avatar"])
        self.assertIsNone(error)

    def test_dynamic_range_failures(self) -> None:
        # Test when state_getter fails for dynamic min/max
        fields = {
            "val": FieldRules(input_type="number", min_expr="non_existent", max_expr="error_expr")
        }

        def failing_getter(expr: str) -> str:
            if expr == "error_expr":
                raise Exception("Boom")
            return "not-a-number"

        # Should fallback gracefully (skip dynamic check)
        data = {"val": "10"}
        cleaned, errors = validate_form(data, fields, failing_getter)
        self.assertEqual(len(errors), 0)

    def test_url_validation(self) -> None:
        fields = {"website": FieldRules(input_type="url")}
        self.assertEqual(
            len(validate_form({"website": "https://google.com"}, fields, lambda x: None)[1]), 0
        )
        self.assertIn("website", validate_form({"website": "not-a-url"}, fields, lambda x: None)[1])

    def test_custom_title_error(self) -> None:
        fields = {"name": FieldRules(required=True, title="NAME_REQUIRED")}
        _, errors = validate_form({"name": ""}, fields, lambda x: None)
        self.assertEqual(errors["name"], "NAME_REQUIRED is required.")

    def test_pydantic_prefix_removal(self) -> None:
        # Trigger a pydantic error that might have "Value error, " prefix
        # Pydantic v2 often has this.
        from pydantic import field_validator

        class PrefixModel(BaseModel):
            val: int

            @field_validator("val")
            @classmethod
            def check_val(cls, v: int) -> int:
                if v < 0:
                    raise ValueError("Must be positive")
                return v

        instance, errors = validate_with_model({"val": -1}, PrefixModel)
        # It should just be "Must be positive" or similar, not "Value error, Must be positive"
        self.assertIn("Must be positive", errors["val"])
        self.assertNotIn("Value error, ", errors["val"])

    def test_pydantic_v1_fallback(self) -> None:
        # Mocking a model that only has parse_obj but not model_validate
        class LegacyModel:
            @classmethod
            def parse_obj(cls, data: dict) -> str:
                return "LegacyInstance"

        # We need to pass it to validate_with_model which expects Type[BaseModel]
        # but it just checks hasattr(model_class, 'model_validate')
        instance, errors = validate_with_model({"x": 1}, LegacyModel)  # type: ignore
        self.assertEqual(instance, "LegacyInstance")

    def test_pydantic_unexpected_exception(self) -> None:
        class BreakingModel:
            @classmethod
            def model_validate(cls, data: dict) -> None:
                raise RuntimeError("Unexpected failure")

        instance, errors = validate_with_model({"x": 1}, BreakingModel)  # type: ignore
        self.assertIn("__all__", errors)
        self.assertIn("Unexpected failure", errors["__all__"])

    def test_upload_id_resolution(self) -> None:
        from unittest.mock import patch

        from pywire.runtime.upload_manager import upload_manager

        with patch.object(upload_manager, "get") as mock_get:
            mock_get.return_value = "ResolvedFile"
            val = form_validator._convert_value({"_upload_id": "123"}, "file")
            self.assertEqual(val, "ResolvedFile")
            mock_get.assert_called_with("123")

            mock_get.return_value = None
            val = form_validator._convert_value({"_upload_id": "missing"}, "file")
            self.assertIsNone(val)

    def test_float_fallback(self) -> None:
        # number conversion that requires float
        val = form_validator._convert_value("1.5", "number")
        self.assertEqual(val, 1.5)
        self.assertIsInstance(val, float)


if __name__ == "__main__":
    unittest.main()
