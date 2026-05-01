"""Runtime helpers for reactive attribute normalization.

Used by codegen to render `class={...}` and `style={...}` bindings whose
runtime value may be a list, tuple, dict, or string. Other attributes
fall through to plain `str(value)`.
"""

from __future__ import annotations

from typing import Any


def _normalize_class(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(str(k) for k, v in value.items() if v)
    if isinstance(value, (list, tuple, set)):
        return " ".join(str(item) for item in value if item)
    return str(value)


def _normalize_style(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            if v is None or v is False:
                continue
            parts.append(f"{k}:{v}")
        return ";".join(parts)
    return str(value)


def normalize_attr(name: str, value: Any) -> str:
    """Render a reactive attribute value as a string.

    Special handling:
    - ``class``: list/tuple/set → space-joined truthy items;
      dict → space-joined keys whose values are truthy.
    - ``style``: dict → ``;``-joined ``k:v`` pairs (skips None/False).
    - Anything else: ``str(value)``.
    """
    if name == "class":
        return _normalize_class(value)
    if name == "style":
        return _normalize_style(value)
    return str(value)
