from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class MissingFieldError:
    """Falsy sentinel for missing form errors."""

    def __bool__(self) -> bool:
        return False

    def __str__(self) -> str:
        return ""

    def __repr__(self) -> str:
        return "MissingFieldError()"

    def __call__(self, *args: Any, **kwargs: Any) -> "MissingFieldError":
        return self

    def __await__(self) -> Any:
        async def _fake():
            return self

        return _fake().__await__()

    def __getattr__(self, _name: str) -> "MissingFieldError":
        return self

    def get(self, _key: str, _default: Any = None) -> "MissingFieldError":
        return self


MISSING_FIELD_ERROR = MissingFieldError()


class ErrorNamespace(dict):
    """Dict-like object that also supports attribute access."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            return super().__getattribute__(name)
        val = self.get(name, MISSING_FIELD_ERROR)
        logger.debug("ERROR-NS-GETATTR: name=%s val=%s type=%s", name, val, type(val))
        return val

    def __getitem__(self, key: str) -> Any:
        return self.get(key, MISSING_FIELD_ERROR)

    def get(self, key: str, default: Any = MISSING_FIELD_ERROR) -> Any:
        if "." not in key:
            return dict.get(self, key, default)

        current: Any = self
        for part in key.split("."):
            if not isinstance(current, dict):
                return default
            if part not in current:
                return default
            current = current[part]
        return current

    def set_path(self, path: str, value: Any) -> None:
        current: Dict[str, Any] = self
        parts = path.split(".")
        for part in parts[:-1]:
            existing = current.get(part)
            if not isinstance(existing, ErrorNamespace):
                existing = ErrorNamespace()
                current[part] = existing
            current = existing
        current[parts[-1]] = value

    def update(self, *args: Any, **kwargs: Any) -> None:
        updates: Dict[str, Any] = {}
        if args:
            if len(args) != 1:
                raise TypeError("update expected at most 1 positional argument")
            updates.update(dict(args[0]))
        updates.update(kwargs)
        for key, value in updates.items():
            if not isinstance(key, str):
                self[key] = value
                continue
            if "." in key:
                self.set_path(key, value)
                continue
            self[key] = value


class FieldError(ErrorNamespace):
    """Structured error object for one field."""

    def __init__(
        self,
        *,
        field: str,
        rule: str,
        message: str,
        source: str,
        params: Optional[Dict[str, Any]] = None,
        native_type: Optional[str] = None,
    ) -> None:
        super().__init__()
        self["field"] = field
        self["rule"] = rule
        self["message"] = message
        self["source"] = source
        self["params"] = ErrorNamespace(params or {})
        self["native_type"] = native_type

    def __bool__(self) -> bool:
        return True

    def __str__(self) -> str:
        return self.get("message", "")


def build_error_namespace(flat_errors: Dict[str, Any]) -> ErrorNamespace:
    root = ErrorNamespace()
    for field_path, err in flat_errors.items():
        value = err
        if isinstance(err, dict) and not isinstance(err, FieldError):
            value = FieldError(
                field=err.get("field", field_path),
                rule=err.get("rule", "model"),
                message=err.get("message", "Invalid value"),
                source=err.get("source", "html5"),
                params=err.get("params", {}),
                native_type=err.get("native_type"),
            )
        root.set_path(field_path, value)
    return root
