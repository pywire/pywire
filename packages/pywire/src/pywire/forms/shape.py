"""Turn a submitted form into model input.

Whitelist and shape in one walk over the model's field specs: only names the
schema knows are read, dotted and indexed names (``address.street``,
``items.0.name``) become nested data, list fields keep every value, an
unticked checkbox is ``False``, and an empty text box counts as not filled in
(so HTML ``required`` and a Pydantic field without a default agree).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Set, Tuple

from pywire.forms.schema import TEXT_KINDS, FieldSpec
from pywire.runtime.files import FileUpload

Flat = Dict[str, List[Any]]

# Hard cap on rows read for one list field, whatever the client sends.
MAX_ROWS = 1000


def normalize(form_data: Mapping[str, Any]) -> Flat:
    """``{name: value | [values]}`` (either transport) -> ``{name: [values]}``."""
    flat: Flat = {}
    for name, value in form_data.items():
        if not isinstance(name, str):
            continue
        values = value if isinstance(value, (list, tuple)) else [value]
        flat.setdefault(name, []).extend(values)
    return flat


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value == "")


def _files(values: List[Any], resolve: Optional[Callable[[Any], Any]]) -> List[Any]:
    out = []
    for v in values:
        if isinstance(v, FileUpload):
            if v.size > 0 or v.filename:
                out.append(v)
        elif resolve is not None and isinstance(v, dict):
            f = resolve(v)
            if f is not None:
                out.append(f)
    return out


def shape(
    spec: FieldSpec,
    flat: Flat,
    *,
    resolve_upload: Optional[Callable[[Any], Any]] = None,
) -> Dict[str, Any]:
    """Build the ``model_validate`` input for a model spec."""
    return _shape_model(spec, flat, "", resolve_upload)


def _shape_model(
    spec: FieldSpec, flat: Flat, prefix: str, resolve: Optional[Callable[[Any], Any]]
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for child in spec.children.values():
        present, value = _shape_field(child, flat, prefix + child.data_key, resolve)
        if present:
            out[child.data_key] = value
    return out


def _has_prefix(flat: Flat, prefix: str) -> bool:
    return any(k.startswith(prefix) for k in flat)


def row_indices(flat: Flat, prefix: str) -> List[int]:
    found: Set[int] = set()
    for key in flat:
        if not key.startswith(prefix):
            continue
        head = key[len(prefix) :].split(".", 1)[0]
        if head.isascii() and head.isdigit() and len(head) <= 6:
            found.add(int(head))
    return sorted(found)[:MAX_ROWS]


def _shape_field(
    spec: FieldSpec, flat: Flat, name: str, resolve: Optional[Callable[[Any], Any]]
) -> Tuple[bool, Any]:
    kind = spec.kind

    if kind == "model":
        if not _has_prefix(flat, name + "."):
            return False, None
        sub = _shape_model(spec, flat, name + ".", resolve)
        if spec.nullable and all(
            _is_empty(v)
            for k, vs in flat.items()
            if k.startswith(name + ".")
            for v in vs
        ):
            return True, None
        return True, sub

    if kind == "list":
        rows = row_indices(flat, name + ".")
        if not rows:
            return False, None
        if spec.max_items is not None:
            rows = rows[: spec.max_items + 1]  # one extra so Pydantic reports it
        assert spec.item is not None
        return True, [
            _shape_model(spec.item, flat, f"{name}.{i}.", resolve) for i in rows
        ]

    values = flat.get(name)

    if kind == "boolean":
        if not values:
            # An unticked box sends nothing. Literal[True] must be ticked, so
            # leave it missing for Pydantic to report.
            return (False, None) if spec.required else (True, False)
        last = values[-1]
        return True, isinstance(last, str) and last.lower() not in (
            "",
            "false",
            "off",
            "0",
        )

    if kind in ("multi", "multichoice"):
        # A checkbox group or multiple select with nothing picked sends
        # nothing at all, which means "none", not "not submitted".
        picked = [v for v in (values or []) if isinstance(v, str) and v != ""]
        if spec.max_items is not None:
            picked = picked[: spec.max_items + 1]
        return True, picked[:MAX_ROWS]

    if kind in ("file", "files"):
        files = _files(values or [], resolve)
        if kind == "files":
            return True, files[:MAX_ROWS]
        if files:
            return True, files[-1]
        return (True, None) if spec.nullable else (False, None)

    if not values:
        return False, None
    last = values[-1]
    if not isinstance(last, str):
        # A file or structured value posted to a text field: not a value.
        return False, None
    if last == "":
        if spec.nullable:
            return True, None
        if kind in TEXT_KINDS and spec.has_default:
            return True, ""
        return False, None
    return True, last
