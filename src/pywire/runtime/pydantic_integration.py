from typing import Any, Dict, Optional, Tuple, Type

from pydantic import BaseModel, ValidationError


def validate_with_model(
    data: Dict[str, Any], model_class: Type[BaseModel]
) -> Tuple[Optional[BaseModel], Dict[str, str]]:
    """
    Attempt to instantiate and validate a Pydantic model.

    Args:
        data: The input dictionary (already type-converted by FormValidator if possible,
              but Pydantic handles its own conversion too).
        model_class: The Pydantic model class to validate against.

    Returns:
        (model_instance, {}) on success.
        (None, {field_name: error_message}) on validation failure.
    """
    try:
        # Pydantic v2 use model_validate, v1 use parse_obj.
        # Let's support v2 primarily, but fallback if needed.
        if hasattr(model_class, "model_validate"):
            instance = model_class.model_validate(data)
        else:
            instance = model_class.parse_obj(data)

        return instance, {}

    except ValidationError as e:
        errors = {}
        for err in e.errors():
            # Extract field name. 'loc' is a tuple like ('field',).
            # Nested fields might be ('parent', 'child').
            # We want to map this back to dotted string for errors dict.
            loc = err.get("loc", ())
            field_name = ".".join(str(part) for part in loc)

            # Simple error message
            msg = err.get("msg", "Invalid value")

            # Remove Pydantic's "Value error, " prefix if present
            if msg.startswith("Value error, "):
                msg = msg[len("Value error, ") :]

            errors[field_name] = msg

        return None, errors
    except Exception as e:
        # Unexpected error during validation
        return None, {"__all__": str(e)}
