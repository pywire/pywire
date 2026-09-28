"""One error vocabulary for forms.

Every error carries a ``code`` named after the browser's ``ValidityState``
flags (``valueMissing``, ``tooShort``, ``rangeOverflow`` ...) so the same
names describe a native constraint failure and a server one. Pydantic's own
error type rides along in ``type``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, Union

from pywire.forms.schema import FieldSpec

Messages = Mapping[str, Union[str, Callable[[Dict[str, Any]], str]]]


@dataclass(frozen=True)
class FieldError:
    code: str
    message: str
    type: str = "custom"

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> Dict[str, str]:
        return {"code": self.code, "message": self.message, "type": self.type}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FieldError":
        return cls(
            code=str(data.get("code", "customError")),
            message=str(data.get("message", "")),
            type=str(data.get("type", "custom")),
        )


# pydantic error type -> (code, default message template)
_BY_TYPE: Dict[str, Tuple[str, str]] = {
    "missing": ("valueMissing", "This field is required"),
    "string_too_short": ("tooShort", "Use at least {min_length} characters"),
    "string_too_long": ("tooLong", "Use {max_length} characters or fewer"),
    "too_short": ("tooShort", "Choose at least {min_length}"),
    "too_long": ("tooLong", "Choose at most {max_length}"),
    "greater_than_equal": ("rangeUnderflow", "Must be {ge} or more"),
    "greater_than": ("rangeUnderflow", "Must be more than {gt}"),
    "less_than_equal": ("rangeOverflow", "Must be {le} or less"),
    "less_than": ("rangeOverflow", "Must be less than {lt}"),
    "multiple_of": ("stepMismatch", "Must be a multiple of {multiple_of}"),
    "string_pattern_mismatch": ("patternMismatch", "Match the requested format"),
    "int_parsing": ("badInput", "Enter a whole number"),
    "int_from_float": ("badInput", "Enter a whole number"),
    "int_type": ("badInput", "Enter a whole number"),
    "float_parsing": ("badInput", "Enter a number"),
    "float_type": ("badInput", "Enter a number"),
    "decimal_parsing": ("badInput", "Enter a number"),
    "decimal_type": ("badInput", "Enter a number"),
    "finite_number": ("badInput", "Enter a number"),
    "bool_parsing": ("badInput", "Choose yes or no"),
    "date_parsing": ("badInput", "Enter a valid date"),
    "date_from_datetime_parsing": ("badInput", "Enter a valid date"),
    "date_type": ("badInput", "Enter a valid date"),
    "datetime_parsing": ("badInput", "Enter a valid date and time"),
    "datetime_from_date_parsing": ("badInput", "Enter a valid date and time"),
    "datetime_type": ("badInput", "Enter a valid date and time"),
    "time_parsing": ("badInput", "Enter a valid time"),
    "time_type": ("badInput", "Enter a valid time"),
    "literal_error": ("badInput", "Choose one of the options"),
    "enum": ("badInput", "Choose one of the options"),
    "url_parsing": ("typeMismatch", "Enter a valid URL"),
    "url_type": ("typeMismatch", "Enter a valid URL"),
    "url_scheme": ("typeMismatch", "Enter a valid URL"),
    "url_too_long": ("typeMismatch", "Enter a valid URL"),
    "is_instance_of": ("badInput", "Choose a file"),
    # UploadField (pywire.forms.uploads)
    "file_too_large": ("fileTooLarge", "Choose a file no larger than {max_size}"),
    "file_type": ("fileType", "Choose a file of type {accept}"),
    "too_many_files": ("tooManyFiles", "Choose at most {max_files} files"),
}


class _SafeCtx(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _render(template: Any, ctx: Dict[str, Any]) -> str:
    if callable(template):
        return str(template(ctx))
    return str(template).format_map(_SafeCtx(ctx))


def map_error(
    err: Mapping[str, Any], spec: Optional[FieldSpec], messages: Messages, path: str
) -> FieldError:
    """Turn one pydantic error dict into a FieldError."""
    etype = str(err.get("type", "custom"))
    ctx: Dict[str, Any] = dict(err.get("ctx") or {})
    code, template = _BY_TYPE.get(etype, ("customError", ""))

    kind = spec.kind if spec is not None else ""
    if kind == "boolean" and etype in ("missing", "literal_error", "bool_parsing"):
        code, template = "valueMissing", "Check this box to continue"
    elif kind == "file" and etype in ("missing", "is_instance_of"):
        code, template = "valueMissing", "Choose a file"
    elif etype in ("value_error", "assertion_error") and "error" in ctx:
        # A ValueError/AssertionError raised by a validator: its own message
        # is the one the user should see, without Pydantic's prefix.
        code = "customError"
        template = str(ctx["error"]) or str(err.get("msg", ""))
    elif spec is not None and spec.input_type == "email" and etype == "value_error":
        code, template = "typeMismatch", "Enter a valid email address"
    elif etype in ("value_error", "assertion_error"):
        code, template = "customError", str(err.get("msg", ""))
    elif not template:
        template = str(err.get("msg", "Invalid value"))

    override = messages.get(f"{path}.{code}") if path else None
    if override is None:
        override = messages.get(code)
    if override is not None:
        template = override
    ctx.pop("error", None)
    return FieldError(code=code, message=_render(template, ctx), type=etype)


def error_path(
    root: FieldSpec, loc: Tuple[Any, ...]
) -> Tuple[str, Optional[FieldSpec]]:
    """Map a pydantic ``loc`` (data keys) to a dotted field path.

    Walks the spec so trailing union tags and item indices of value lists
    (``("tags", 2)``) land on the field itself.
    """
    parts: List[str] = []
    spec: Optional[FieldSpec] = root
    for item in loc:
        if spec is None:
            break
        if spec.kind == "model" and isinstance(item, str):
            child = next(
                (c for c in spec.children.values() if c.data_key == item), None
            )
            if child is None:
                break
            parts.append(child.key)
            spec = child
        elif spec.kind == "list" and isinstance(item, int):
            parts.append(str(item))
            spec = spec.item
        else:
            break
    return ".".join(parts), (spec if parts else None)
