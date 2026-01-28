"""Server-side form validation matching HTML5 constraints."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from pywire.runtime.files import FileUpload
from pywire.runtime.upload_manager import upload_manager


@dataclass
class FieldRules:
    """Runtime validation rules for a single field."""

    required: bool = False
    required_expr: Optional[str] = None  # Python expression for conditional required
    pattern: Optional[str] = None
    minlength: Optional[int] = None
    maxlength: Optional[int] = None
    min_value: Optional[str] = None
    min_expr: Optional[str] = None  # Python expression for dynamic min
    max_value: Optional[str] = None
    max_expr: Optional[str] = None  # Python expression for dynamic max
    step: Optional[str] = None
    input_type: str = "text"
    title: Optional[str] = None  # Custom error message
    max_size: Optional[int] = None  # Max file size in bytes
    allowed_types: Optional[List[str]] = None  # Allowed MIME types or extensions


@dataclass
class FormValidationSchema:
    """Runtime schema containing all validation rules for a form."""

    fields: Dict[str, FieldRules]
    model_name: Optional[str] = None


class FormValidator:
    """Server-side form validation matching HTML5 constraints."""

    # Email regex (simplified but sufficient for most cases)
    EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

    # URL regex (simplified)
    URL_PATTERN = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)

    def validate_field(
        self,
        name: str,
        value: Any,
        rules: FieldRules,
        state_getter: Optional[Callable[[str], Any]] = None,
    ) -> Optional[str]:
        """
        Validate a single field against rules.

        Args:
            name: Field name
            value: Field value (string from form)
            rules: Validation rules
            state_getter: Optional function to evaluate expressions against page state

        Returns:
            Error message string, or None if valid.
        """
        # Handle conditional required
        is_required = rules.required
        if rules.required_expr and state_getter:
            try:
                is_required = bool(state_getter(rules.required_expr))
            except Exception:
                is_required = rules.required

        # Check required
        if is_required:
            if value is None or (isinstance(value, str) and value.strip() == ""):
                return rules.title or "This field is required"

        # If empty and not required, skip other validations
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return None

        str_value = str(value).strip()

        # Pattern validation
        if rules.pattern:
            try:
                if not re.fullmatch(rules.pattern, str_value):
                    return rules.title or "Value does not match the required pattern"
            except re.error:
                pass  # Invalid regex, skip

        # Length validations
        if rules.minlength is not None:
            if len(str_value) < rules.minlength:
                return rules.title or f"Must be at least {rules.minlength} characters"

        if rules.maxlength is not None:
            if len(str_value) > rules.maxlength:
                return rules.title or f"Must be at most {rules.maxlength} characters"

        # Type-based validation
        if rules.input_type == "email":
            if not self.EMAIL_PATTERN.match(str_value):
                return rules.title or "Please enter a valid email address"

        elif rules.input_type == "url":
            if not self.URL_PATTERN.match(str_value):
                return rules.title or "Please enter a valid URL"

        elif rules.input_type == "number":
            return self._validate_number(str_value, rules, state_getter)

        elif rules.input_type == "date":
            return self._validate_date(str_value, rules, state_getter)

        elif rules.input_type == "file":
            # File validation
            if isinstance(value, FileUpload):
                # Check size
                if rules.max_size is not None and value.size > rules.max_size:
                    size_mb = rules.max_size / (1024 * 1024)
                    return rules.title or f"File is too large (max {size_mb:.1f}MB)"

                # Check type
                if rules.allowed_types:
                    # Simple MIME type check
                    # rules.allowed_types is list like ['image/*', 'application/pdf', '.jpg']
                    allowed = False
                    for pattern in rules.allowed_types:
                        pattern = pattern.strip()
                        if pattern.startswith("."):
                            # Extension check
                            if value.filename.lower().endswith(pattern.lower()):
                                allowed = True
                                break
                        elif pattern.endswith("/*"):
                            # Wildcard MIME check (e.g. image/*)
                            base_type = pattern[:-2]  # remove /*
                            if value.content_type.startswith(base_type):
                                allowed = True
                                break
                        else:
                            # Exact MIME check
                            if value.content_type == pattern:
                                allowed = True
                                break

                    if not allowed:
                        return (
                            rules.title
                            or f"File type not allowed. Accepted: {', '.join(rules.allowed_types)}"
                        )

        # Range validation for non-typed fields
        if rules.input_type == "text":
            # Only apply if min/max look numeric
            if rules.min_value or rules.max_value or rules.min_expr or rules.max_expr:
                try:
                    num_value = Decimal(str_value)
                    return self._validate_numeric_range(num_value, rules, state_getter)
                except InvalidOperation:
                    pass  # Not a number, skip range validation

        return None

    def _validate_number(
        self, str_value: str, rules: FieldRules, state_getter: Optional[Callable[[str], Any]] = None
    ) -> Optional[str]:
        """Validate a number input."""
        try:
            num_value = Decimal(str_value)
        except InvalidOperation:
            return rules.title or "Please enter a valid number"

        return self._validate_numeric_range(num_value, rules, state_getter)

    def _validate_numeric_range(
        self,
        num_value: Decimal,
        rules: FieldRules,
        state_getter: Optional[Callable[[str], Any]] = None,
    ) -> Optional[str]:
        """Validate numeric range constraints."""
        # Get min value (static or dynamic)
        min_val = None
        if rules.min_expr and state_getter:
            try:
                min_val = Decimal(str(state_getter(rules.min_expr)))
            except (InvalidOperation, Exception):
                pass
        elif rules.min_value:
            try:
                min_val = Decimal(rules.min_value)
            except InvalidOperation:
                pass

        if min_val is not None and num_value < min_val:
            return rules.title or f"Value must be at least {min_val}"

        # Get max value (static or dynamic)
        max_val = None
        if rules.max_expr and state_getter:
            try:
                max_val = Decimal(str(state_getter(rules.max_expr)))
            except (InvalidOperation, Exception):
                pass
        elif rules.max_value:
            try:
                max_val = Decimal(rules.max_value)
            except InvalidOperation:
                pass

        if max_val is not None and num_value > max_val:
            return rules.title or f"Value must be at most {max_val}"

        # Step validation
        if rules.step:
            try:
                step = Decimal(rules.step)
                if step > 0:
                    base = min_val if min_val is not None else Decimal("0")
                    diff = num_value - base
                    if diff % step != 0:
                        return rules.title or f"Value must be a multiple of {step}"
            except InvalidOperation:
                pass

        return None

    def _validate_date(
        self, str_value: str, rules: FieldRules, state_getter: Optional[Callable[[str], Any]] = None
    ) -> Optional[str]:
        """Validate a date input."""
        try:
            date_value = date.fromisoformat(str_value)
        except ValueError:
            return rules.title or "Please enter a valid date (YYYY-MM-DD)"

        # Get min date (static or dynamic)
        min_date = None
        if rules.min_expr and state_getter:
            try:
                min_str = str(state_getter(rules.min_expr))
                min_date = date.fromisoformat(min_str)
            except (ValueError, Exception):
                pass
        elif rules.min_value:
            try:
                min_date = date.fromisoformat(rules.min_value)
            except ValueError:
                pass

        if min_date is not None and date_value < min_date:
            return rules.title or f"Date must be on or after {min_date.isoformat()}"

        # Get max date (static or dynamic)
        max_date = None
        if rules.max_expr and state_getter:
            try:
                max_str = str(state_getter(rules.max_expr))
                max_date = date.fromisoformat(max_str)
            except (ValueError, Exception):
                pass
        elif rules.max_value:
            try:
                max_date = date.fromisoformat(rules.max_value)
            except ValueError:
                pass

        if max_date is not None and date_value > max_date:
            return rules.title or f"Date must be on or before {max_date.isoformat()}"

        return None

    def validate_form(
        self,
        data: Dict[str, Any],
        schema: Dict[str, FieldRules],
        state_getter: Callable[[str], Any],
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        """
        Validate data against schema.
        Returns: (cleaned_data, errors)
        """
        errors: Dict[str, str] = {}
        cleaned_data: Dict[str, Any] = {}

        # 1. Validate fields present in schema
        for field_name, rules in schema.items():
            value = data.get(field_name)

            # Helper to evaluate rules against state
            def eval_rule(attr_name: str) -> Any:
                expr = getattr(rules, f"{attr_name}_expr")
                if expr:
                    return state_getter(expr)
                return getattr(rules, attr_name)

            # Check required
            is_required = eval_rule("required")
            if is_required and (value is None or value == ""):
                errors[field_name] = f"{rules.title or field_name} is required."
                continue

            # If empty and not required, skip other validations
            if value is None or value == "":
                if rules.input_type == "checkbox":
                    cleaned_data[field_name] = False
                else:
                    cleaned_data[field_name] = None
                continue

            # Type conversion (strings to int/float/bool)
            try:
                converted_value = self._convert_value(value, rules.input_type)
                cleaned_data[field_name] = converted_value
            except ValueError:
                errors[field_name] = (
                    f"{rules.title or field_name} must be a valid {rules.input_type}."
                )
                continue

            # Validate rules against converted value
            error = self.validate_field(
                field_name, converted_value, rules, state_getter
            )  # Use original state_getter for validate_field
            if error:
                errors[field_name] = error

        # 2. Pass through data not in schema?
        # For strict typing, maybe we only want schema fields?
        # But for flexibility, let's merge original data for non-schema fields.
        final_data = data.copy()
        final_data.update(cleaned_data)

        return final_data, errors

    def _convert_value(self, value: Any, input_type: str) -> Any:
        """Convert string value to appropriate type."""
        if value is None or value == "":
            return None

        if input_type == "number":
            # Try int first, then float? Or just float?
            # HTML input type="number" can be either.
            try:
                if isinstance(value, str) and "." in value:
                    return float(value)
                return int(value)
            except ValueError:
                # If int conversion fails, try float as a last resort
                return float(value)

        elif input_type == "checkbox":
            # Checkbox value usually "on" or "true" string, but handled by client framework?
            # If it comes from FormData, unchecked might be missing (handled in
            # validate_form required check).
            # Checked might be "on".
            # Convert to boolean. Common values for "true" are "on", "true", 1.
            if isinstance(value, str):
                return value.lower() in ("on", "true", "1")
            return bool(value)

        elif input_type == "file":
            # File uploads come as dicts from client.
            # If it has _upload_id, resolve it via UploadManager.
            # If it has content (old way), use from_dict.
            if isinstance(value, dict):
                if "_upload_id" in value:
                    file = upload_manager.get(value["_upload_id"])
                    if file:
                        return file
                    return None  # Pending or expired?
                elif "content" in value:
                    return FileUpload.from_dict(value)
            return value

        return value

    def convert_to_type(self, value: Any, target_type: Type) -> Any:
        """Convert value to specific Python type hints (e.g. Enums)."""
        if value is None:
            return None

        # Enum conversion
        if isinstance(target_type, type) and issubclass(target_type, Enum):
            # Try matching by value first
            try:
                return target_type(value)
            except ValueError:
                pass

            # Try matching by name
            if isinstance(value, str):
                try:
                    return target_type[value]
                except KeyError:
                    pass
                try:
                    return target_type[value.upper()]
                except KeyError:
                    pass

            # Return original if generic match fails, likely invalid
            return value

        return value

        return value

    @staticmethod
    def parse_nested_data(flat_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse flat form data with dot notation into nested dicts.

        Example:
            {'customer.name': 'John', 'customer.email': 'john@example.com'}
            ->
            {'customer': {'name': 'John', 'email': 'john@example.com'}}
        """
        result: Dict[str, Any] = {}

        for key, value in flat_data.items():
            parts = key.split(".")
            current = result

            for i, part in enumerate(parts[:-1]):
                if part not in current:
                    current[part] = {}
                current = current[part]

            current[parts[-1]] = value

        return result


# Global validator instance
form_validator = FormValidator()
