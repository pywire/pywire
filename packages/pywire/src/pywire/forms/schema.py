"""Field specs derived from a Pydantic model.

The model is the contract. ``model_json_schema(mode="validation")`` is
Pydantic's public description of what the model accepts, so the HTML
attributes rendered for the browser come from it rather than from field
metadata internals. The server never trusts those attributes: it validates
with the model itself (see ``shape`` and ``Form._validate``).
"""

from __future__ import annotations

import enum
import math
import types
from dataclasses import dataclass, field
from typing import Annotated, Any, Dict, Optional, Tuple, Union, get_args, get_origin

from pydantic import BaseModel

from pywire.runtime.uploads import Upload

# kind -> default HTML control. ``select`` is a tag, not an input type.
TEXT_KINDS = frozenset({"text", "secret"})
SCALAR_KINDS = frozenset(
    {"text", "secret", "integer", "number", "choice", "date", "datetime", "time"}
)
_FORMAT_KIND = {
    "date": ("date", "date"),
    "date-time": ("datetime", "datetime-local"),
    "time": ("time", "time"),
    "email": ("text", "email"),
    "uri": ("text", "url"),
    "password": ("secret", "password"),
    "binary": ("file", "file"),
}


@dataclass(frozen=True)
class Option:
    """One choice of a ``Literal`` or ``Enum`` field."""

    value: str
    label: str


@dataclass
class FieldSpec:
    """What one model field accepts, and how it renders."""

    key: str  # Python attribute name ("" for list items)
    data_key: str  # key in the validation input (alias-aware)
    kind: str
    input_type: str
    required: bool = False
    nullable: bool = False
    has_default: bool = False
    default: Any = None
    attrs: Dict[str, str] = field(default_factory=dict)
    options: Tuple[Option, ...] = ()
    label: str = ""
    description: Optional[str] = None
    model: Optional["ModelSpec"] = None  # kind "model"
    item: Optional["FieldSpec"] = None  # kind "list" (rows), "multi" (values)
    max_items: Optional[int] = None

    @property
    def multiple(self) -> bool:
        return self.kind in ("multichoice", "multi", "files")

    @property
    def children(self) -> Dict[str, "FieldSpec"]:
        return self.model.children if self.model is not None else {}


class ModelSpec:
    """Field specs for one model class, built once and shared.

    Children are built lazily so self-referencing models don't recurse.
    """

    def __init__(self, model: type[BaseModel]) -> None:
        self.model = model
        self._children: Optional[Dict[str, FieldSpec]] = None

    @property
    def children(self) -> Dict[str, FieldSpec]:
        if self._children is None:
            self._children = _build_children(self.model)
        return self._children


_SPECS: Dict[type[BaseModel], ModelSpec] = {}


def model_spec(model: type[BaseModel]) -> ModelSpec:
    spec = _SPECS.get(model)
    if spec is None:
        spec = _SPECS[model] = ModelSpec(model)
    return spec


def root_spec(model: type[BaseModel]) -> FieldSpec:
    return FieldSpec(
        key="", data_key="", kind="model", input_type="", model=model_spec(model)
    )


def humanize(name: str) -> str:
    """``first_name`` -> ``First name`` (sentence case, not Title Case)."""
    text = str(name).replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else text


# --- annotation helpers ----------------------------------------------------


def _unwrap(annotation: Any) -> Tuple[Any, bool]:
    """Strip ``Annotated`` and ``Optional``; return (base, nullable)."""
    nullable = False
    while True:
        origin = get_origin(annotation)
        if origin is Annotated:
            annotation = get_args(annotation)[0]
            continue
        if origin is Union or origin is types.UnionType:
            args = [a for a in get_args(annotation) if a is not type(None)]
            if len(args) < len(get_args(annotation)):
                nullable = True
            if len(args) == 1:
                annotation = args[0]
                continue
        return annotation, nullable


def _item_annotation(annotation: Any) -> Any:
    base, _ = _unwrap(annotation)
    if get_origin(base) in (list, set, frozenset, tuple):
        args = get_args(base)
        if args:
            return args[0]
    return None


def _model_class(annotation: Any) -> Optional[type[BaseModel]]:
    base, _ = _unwrap(annotation)
    if isinstance(base, type) and issubclass(base, BaseModel):
        return base
    return None


def _is_upload(annotation: Any) -> bool:
    base, _ = _unwrap(annotation)
    return isinstance(base, type) and issubclass(base, Upload)


def _enum_class(annotation: Any) -> Optional[type[enum.Enum]]:
    base, _ = _unwrap(annotation)
    if isinstance(base, type) and issubclass(base, enum.Enum):
        return base
    return None


# --- JSON schema helpers -----------------------------------------------------


def _deref(schema: Dict[str, Any], defs: Dict[str, Any]) -> Dict[str, Any]:
    seen = 0
    while "$ref" in schema and seen < 32:
        name = schema["$ref"].rsplit("/", 1)[-1]
        extra = {k: v for k, v in schema.items() if k != "$ref"}
        schema = {**defs.get(name, {}), **extra}
        seen += 1
    return schema


def _split_nullable(
    schema: Dict[str, Any], defs: Dict[str, Any]
) -> Tuple[Dict[str, Any], bool]:
    schema = _deref(schema, defs)
    branches = schema.get("anyOf") or schema.get("oneOf")
    if not branches:
        return schema, schema.get("type") == "null"
    outer = {k: v for k, v in schema.items() if k not in ("anyOf", "oneOf")}
    real = [_deref(b, defs) for b in branches if b.get("type") != "null"]
    nullable = len(real) < len(branches)
    if not real:
        return outer, True
    # Decimal is number|string: the number branch carries the constraints.
    chosen = next((b for b in real if b.get("type") in ("number", "integer")), real[0])
    return {**chosen, **outer}, nullable


def _num(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# Constructs a browser can't compile in the ``pattern`` attribute (JS ``v``
# flag), or that mean something else there. When a pattern uses one, the
# attribute is left off and only the server enforces it.
_PY_ONLY = ("(?P<", "(?P=", "(?#", "(?>", "(?i", "(?m", "(?s", "(?x", "(?a", "(?u")
_PY_ONLY_ESCAPES = ("\\A", "\\Z", "\\z")
_V_FLAG_CLASS_RESERVED = set("()[{}/|")
_V_FLAG_DOUBLES = (
    "&&", "!!", "##", "$$", "%%", "**", "++", ",,", "..", "::", ";;",
    "<<", "==", ">>", "??", "@@", "^^", "``", "~~",
)  # fmt: skip


def html_pattern(pattern: str) -> Optional[str]:
    """The HTML ``pattern`` for a Pydantic pattern, or None.

    Pydantic searches (``re.search``) while HTML matches the whole value, so
    only a pattern anchored at both ends means the same thing in both places.
    """
    if not (pattern.startswith("^") and pattern.endswith("$")):
        return None
    if pattern.endswith("\\$") and not pattern.endswith("\\\\$"):
        return None
    if any(tok in pattern for tok in _PY_ONLY + _PY_ONLY_ESCAPES):
        return None
    body = pattern[1:-1]
    i, in_class, class_start = 0, False, 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            i += 2
            continue
        if in_class:
            if ch == "]":
                in_class = False
            elif ch in _V_FLAG_CLASS_RESERVED:
                return None
            elif ch == "-" and (i == class_start or body[i + 1 : i + 2] == "]"):
                return None
            elif body[i : i + 2] in _V_FLAG_DOUBLES:
                return None
        elif ch == "[":
            in_class = True
            class_start = i + 1
            if body[i + 1 : i + 2] == "^":
                class_start += 1
        i += 1
    return body


def _constraint_attrs(kind: str, schema: Dict[str, Any]) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    if kind in TEXT_KINDS:
        if "minLength" in schema:
            attrs["minlength"] = str(schema["minLength"])
        if "maxLength" in schema:
            attrs["maxlength"] = str(schema["maxLength"])
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            html = html_pattern(pattern)
            if html is not None:
                attrs["pattern"] = html
    elif kind in ("integer", "number"):
        is_int = kind == "integer"
        low = schema.get("minimum")
        high = schema.get("maximum")
        if is_int and "exclusiveMinimum" in schema:
            low = math.floor(schema["exclusiveMinimum"]) + 1
        if is_int and "exclusiveMaximum" in schema:
            high = math.ceil(schema["exclusiveMaximum"]) - 1
        if low is not None:
            attrs["min"] = _num(low)
        if high is not None:
            attrs["max"] = _num(high)
        step = schema.get("multipleOf")
        # HTML steps count from ``min``; Pydantic's multiple_of counts from 0.
        aligned = step is not None and (
            low is None or math.isclose(low / step, round(low / step))
        )
        if aligned:
            attrs["step"] = _num(step)
        elif not is_int:
            attrs["step"] = "any"
        attrs["inputmode"] = "numeric" if is_int else "decimal"
    elif kind in ("file", "files"):
        # Set by UploadField (pywire.forms.uploads).
        if isinstance(schema.get("x-accept"), str):
            attrs["accept"] = schema["x-accept"]
        if isinstance(schema.get("x-max-size"), int):
            attrs["data-pw-max-size"] = str(schema["x-max-size"])
    return attrs


def _options(
    schema: Dict[str, Any], enum_cls: Optional[type[enum.Enum]]
) -> Tuple[Option, ...]:
    values = schema.get("enum")
    if values is None and "const" in schema:
        values = [schema["const"]]
    if not values:
        return ()
    labels: Dict[str, str] = {}
    if enum_cls is not None:
        for member in enum_cls:
            text = member.value if isinstance(member.value, str) else member.name
            labels[str(member.value)] = humanize(str(text).lower())
    return tuple(
        Option(value=str(v), label=labels.get(str(v)) or humanize(str(v)))
        for v in values
    )


def _kind(
    schema: Dict[str, Any], annotation: Any
) -> Tuple[str, str]:  # (kind, input_type)
    if _is_upload(annotation):
        return "file", "file"
    typ = schema.get("type")
    if "enum" in schema or ("const" in schema and typ != "boolean"):
        return "choice", "select"
    if typ == "boolean":
        return "boolean", "checkbox"
    if typ == "integer":
        return "integer", "number"
    if typ == "number":
        return "number", "number"
    if typ == "string":
        if schema.get("writeOnly"):
            return "secret", "password"
        return _FORMAT_KIND.get(schema.get("format", ""), ("text", "text"))
    return "text", "text"


def _data_key(name: str, info: Any, properties: Dict[str, Any]) -> Optional[str]:
    candidates = []
    alias = getattr(info, "validation_alias", None)
    if isinstance(alias, str):
        candidates.append(alias)
    elif alias is not None and hasattr(alias, "choices"):
        first = alias.choices[0] if alias.choices else None
        if isinstance(first, str):
            candidates.append(first)
    if isinstance(getattr(info, "alias", None), str):
        candidates.append(info.alias)
    candidates.append(name)
    return next((c for c in candidates if c in properties), None)


def _build_children(model: type[BaseModel]) -> Dict[str, FieldSpec]:
    schema = model.model_json_schema(mode="validation")
    defs = schema.get("$defs", {})
    schema = _deref(schema, defs)
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    children: Dict[str, FieldSpec] = {}
    for name, info in model.model_fields.items():
        data_key = _data_key(name, info, properties)
        if data_key is None:
            # Not in the schema (e.g. SkipJsonSchema): server-owned, so the
            # client can never set it.
            continue
        children[name] = _field_spec(
            name, data_key, info, properties[data_key], defs, data_key in required
        )
    return children


def _field_spec(
    name: str,
    data_key: str,
    info: Any,
    raw_schema: Dict[str, Any],
    defs: Dict[str, Any],
    in_required: bool,
) -> FieldSpec:
    annotation = info.annotation
    schema, nullable = _split_nullable(raw_schema, defs)
    label = info.title or humanize(name)
    has_default = not info.is_required()
    default = info.get_default(call_default_factory=True) if has_default else None

    spec = _spec_for(schema, annotation, nullable, defs)
    spec.key = name
    spec.data_key = data_key
    spec.label = label
    spec.description = info.description
    spec.has_default = has_default
    spec.default = default
    spec.nullable = nullable
    spec.required = _html_required(spec, schema, in_required)
    return spec


def _spec_for(
    schema: Dict[str, Any], annotation: Any, nullable: bool, defs: Dict[str, Any]
) -> FieldSpec:
    if schema.get("type") == "array" or _item_annotation(annotation) is not None:
        item_ann = _item_annotation(annotation)
        items, _ = _split_nullable(schema.get("items", {}), defs)
        max_items = schema.get("maxItems")
        if _is_upload(item_ann):
            return FieldSpec(
                "",
                "",
                "files",
                "file",
                attrs=_constraint_attrs("files", items),
                max_items=max_items,
            )
        row_model = _model_class(item_ann)
        if row_model is not None:
            return FieldSpec(
                "",
                "",
                "list",
                "",
                item=FieldSpec("", "", "model", "", model=model_spec(row_model)),
                max_items=max_items,
            )
        item = _spec_for(items, item_ann, False, defs)
        if item.kind == "choice":
            return FieldSpec(
                "",
                "",
                "multichoice",
                "select",
                options=item.options,
                item=item,
                max_items=max_items,
            )
        return FieldSpec(
            "", "", "multi", item.input_type, item=item, max_items=max_items
        )

    nested = _model_class(annotation)
    if nested is not None:
        return FieldSpec("", "", "model", "", model=model_spec(nested))

    kind, input_type = _kind(schema, annotation)
    options: Tuple[Option, ...] = ()
    if kind == "choice":
        options = _options(schema, _enum_class(annotation))
    return FieldSpec(
        "",
        "",
        kind,
        input_type,
        attrs=_constraint_attrs(kind, schema),
        options=options,
    )


def _html_required(spec: FieldSpec, schema: Dict[str, Any], in_required: bool) -> bool:
    if spec.kind == "boolean":
        # A plain bool is False when unchecked; only Literal[True] must be ticked.
        return schema.get("const") is True
    if spec.kind in ("model", "list", "multi", "multichoice", "files"):
        return False
    return in_required and not spec.nullable
