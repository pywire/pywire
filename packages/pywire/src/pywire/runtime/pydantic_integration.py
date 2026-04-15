from typing import Any, Dict, List, Tuple, Type, Union, get_args, get_origin

try:
    from pydantic import BaseModel, ValidationError
except ImportError:
    BaseModel = None  # type: ignore[assignment,misc]
    ValidationError = None  # type: ignore[assignment,misc]

from pywire.runtime.form_errors import FieldError
from pywire.runtime.files import FileUpload
from pywire.runtime.upload_manager import upload_manager


def _require_pydantic() -> None:
    if BaseModel is None:
        raise ImportError(
            "Pydantic is required for form validation. "
            "Install it with: pip install pywire[forms]"
        )


class UploadResolutionError(ValueError):
    def __init__(self, path: str):
        super().__init__(f"{path} upload is missing or expired")
        self.path = path


def _normalize_pydantic_rule(err_type: str) -> str:
    if err_type == "missing":
        return "required"
    if err_type in {"string_too_short"}:
        return "minlength"
    if err_type in {"string_too_long"}:
        return "maxlength"
    if err_type in {"string_pattern_mismatch"}:
        return "pattern"
    if "date" in err_type:
        return "bad_date"
    if "int_parsing" in err_type or "float_parsing" in err_type or "number" in err_type:
        return "bad_number"
    if "url" in err_type or "email" in err_type:
        return "type_mismatch"
    return "model"


def validate_with_model(
    data: Dict[str, Any], model_class: "Type[Any]"
) -> "Tuple[Any, Dict[str, FieldError]]":
    """
    Attempt to instantiate and validate a Pydantic model.

    Args:
        data: The input dictionary (already type-converted by FormValidator if possible,
              but Pydantic handles its own conversion too).
        model_class: The Pydantic model class to validate against.

    Returns:
        (model_instance, {}) on success.
        (None, {field_name: FieldError}) on validation failure.
    """
    _require_pydantic()
    try:
        # Pydantic v2 use model_validate, v1 use parse_obj.
        # Let's support v2 primarily, but fallback if needed.
        # Expand dot notation (e.g. "address.street" -> {"address": {"street": ...}})
        expanded_data = _expand_dots(data)
        expanded_data = _resolve_upload_payload(expanded_data)

        if hasattr(model_class, "model_validate"):
            instance = model_class.model_validate(expanded_data)
        else:
            instance = model_class.parse_obj(expanded_data)

        return instance, {}

    except UploadResolutionError as e:
        field_name = e.path or "__all__"
        return (
            None,
            {
                field_name: FieldError(
                    field=field_name,
                    rule="upload_missing",
                    message=str(e),
                    source="pydantic",
                    params={},
                    native_type="upload_missing",
                )
            },
        )
    except ValidationError as e:  # type: ignore[misc]
        errors: Dict[str, FieldError] = {}
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

            err_type = str(err.get("type", "model"))
            rule = _normalize_pydantic_rule(err_type)
            errors[field_name] = FieldError(
                field=field_name,
                rule=rule,
                message=msg,
                source="pydantic",
                params=err.get("ctx", {}),
                native_type=err_type,
            )

        return None, errors
    except Exception as e:
        # Unexpected error during validation
        return (
            None,
            {
                "__all__": FieldError(
                    field="__all__",
                    rule="model",
                    message=str(e),
                    source="pydantic",
                    params={},
                    native_type="exception",
                )
            },
        )


def _expand_dots(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Expand flat dictionary with dot notation into nested dictionary.
    'address.street': 'value' -> {'address': {'street': 'value'}}
    """
    result = {}
    for key, value in data.items():
        if "." in key:
            parts = key.split(".")
            current = result
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
                if not isinstance(current, dict):
                    # Conflict: key exists but is not a dict (e.g. "user" and "user.name")
                    # Simple approach: assume no conflicts for now.
                    pass
            current[parts[-1]] = value
        else:
            result[key] = value
    return result


def extract_field_rules(model_class: "Type[Any]") -> Dict[str, Dict[str, Any]]:
    """
    Extract HTML5 validation rules from a Pydantic model.
    Returns: {field_name: {attribute_name: value}}
    """
    rules = {}

    # Support Pydantic v2 model_fields, fallback to v1 __fields__
    if hasattr(model_class, "model_fields"):
        fields = model_class.model_fields
    elif hasattr(model_class, "__fields__"):
        fields = model_class.__fields__
    else:
        fields = {}

    for name, field in fields.items():
        field_rules = {}

        # Required check
        is_required = False
        if hasattr(field, "is_required"):  # Pydantic v2
            is_required = field.is_required()
        elif hasattr(field, "required"):  # Pydantic v1
            is_required = field.required

        if is_required:
            field_rules["required"] = True

        # Metadata extraction (min_length, max_length, pattern, etc.)
        # Pydantic v2 stores this in field.metadata ideally
        metadata = getattr(field, "metadata", [])
        annotation = getattr(field, "annotation", None)
        if annotation is None and hasattr(field, "outer_type_"):
            annotation = field.outer_type_

        is_file_field, is_multiple_files = _is_file_annotation(annotation)
        if is_file_field:
            field_rules["input_type"] = "file"
            field_rules["multiple"] = is_multiple_files

        extras = getattr(field, "json_schema_extra", None)
        if not extras and hasattr(field, "field_info"):
            extras = getattr(field.field_info, "extra", None)
        if isinstance(extras, dict):
            for key in (
                "max_size",
                "min_size",
                "max_files",
                "allowed_types",
                "allowed_names",
                "multiple",
            ):
                if key in extras:
                    field_rules[key] = extras[key]

        for meta in metadata:
            # Annotated[str, Field(max_length=10)] -> meta is StringConstraints (v2)
            if hasattr(meta, "max_length") and meta.max_length is not None:
                field_rules["maxlength"] = meta.max_length
            if hasattr(meta, "min_length") and meta.min_length is not None:
                field_rules["minlength"] = meta.min_length
            if hasattr(meta, "pattern") and meta.pattern is not None:
                field_rules["pattern"] = meta.pattern
            if hasattr(meta, "ge") and meta.ge is not None:
                field_rules["min"] = meta.ge
            if hasattr(meta, "le") and meta.le is not None:
                field_rules["max"] = meta.le
            if hasattr(meta, "gt") and meta.gt is not None:
                # HTML min is inclusive, so gt(5) -> min(5.00001)? Or just ignore?
                # For integers, gt(5) -> min(6)
                pass

        rules[name] = field_rules

    return rules


def _is_file_annotation(annotation: Any) -> Tuple[bool, bool]:
    if annotation is FileUpload:
        return True, False

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin in (list, List):
        if len(args) == 1 and args[0] is FileUpload:
            return True, True
        return False, False

    if origin in (Union,):
        non_none = [arg for arg in args if arg is not type(None)]
        if len(non_none) == 1:
            return _is_file_annotation(non_none[0])

    return False, False


def _resolve_upload_payload(value: Any, path: str = "") -> Any:
    if isinstance(value, dict):
        if "_upload_id" in value:
            upload_id = value.get("_upload_id")
            if isinstance(upload_id, str):
                resolved = upload_manager.get(upload_id)
                if resolved is not None:
                    return resolved
            raise UploadResolutionError(path or "__all__")
        if "content" in value:
            return FileUpload.from_dict(value)
        return {
            key: _resolve_upload_payload(val, f"{path}.{key}" if path else key)
            for key, val in value.items()
        }

    if isinstance(value, list):
        resolved_list = []
        for idx, item in enumerate(value):
            item_path = f"{path}[{idx}]" if path else f"[{idx}]"
            resolved_list.append(_resolve_upload_payload(item, item_path))
        return resolved_list

    return value
