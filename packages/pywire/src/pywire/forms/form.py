"""``form(Model)``: a model-first, reactive form bound with ``$bind``.

The DOM holds the draft and the server holds the rules. Every submit carries
the whole form, so validation never needs a stored draft: the same pipeline
serves socket events, stateless snapshots and native POSTs.
"""

from __future__ import annotations

import datetime as _dt
import decimal
import difflib
import enum
import inspect
import logging
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Generic,
    Iterator,
    List,
    Literal,
    Mapping,
    Optional,
    Tuple,
    TypeVar,
    Union,
)

from pydantic import BaseModel, SecretBytes, SecretStr, TypeAdapter, ValidationError

from pywire.core.wire import WirePrimitive
from pywire.forms.errors import FieldError, Messages, error_path, map_error
from pywire.forms.schema import FieldSpec, Option, root_spec
from pywire.forms.shape import MAX_ROWS, Flat, normalize, shape

logger = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)
T = TypeVar("T")

Path = Tuple[Union[str, int], ...]

# A submit button's name for form actions that aren't a submit: adding or
# removing a list row ("add:items", "remove:items.2"), a wizard's "back".
ACTION = "__pywire_action"

# Names on Form itself. A model field with one of these names is still
# reachable as ``form.fields.<name>`` or ``form["<name>"]``.
FORM_MEMBERS = frozenset(
    {
        "model",
        "value",
        "valid",
        "error",
        "errors",
        "dirty",
        "submitted",
        "fields",
        "load",
        "reset",
        # Wizard (pywire.forms.wizard)
        "step",
        "steps",
        "on_first_step",
        "on_last_step",
        "back_button",
    }
)
# Names on BoundField. Same rule: a nested model's field with one of these
# names is reachable as ``field.fields.<name>``. Kept few and unusual so
# common model fields (name, id, description) never clash.
FIELD_MEMBERS = frozenset(
    {
        "html_name",
        "html_id",
        "error_id",
        "label",
        "help",
        "required",
        "options",
        "value",
        "raw",
        "error",
        "errors",
        "attrs",
        "fields",
        "add_button",
        "remove_button",
    }
)


def _is_secret(spec: FieldSpec) -> bool:
    return spec.kind == "secret"


def _to_html(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (SecretStr, SecretBytes)):
        return ""
    if isinstance(value, bool):
        return "true" if value else ""
    if isinstance(value, enum.Enum):
        return _to_html(value.value)
    if isinstance(value, _dt.datetime):
        if value.tzinfo is not None:
            value = value.replace(tzinfo=None)
        spec = "minutes" if not value.second and not value.microsecond else "seconds"
        return value.isoformat(timespec=spec)
    if isinstance(value, _dt.time):
        spec = "minutes" if not value.second and not value.microsecond else "seconds"
        return value.replace(tzinfo=None).isoformat(timespec=spec)
    if isinstance(value, (_dt.date, decimal.Decimal)):
        return value.isoformat() if isinstance(value, _dt.date) else str(value)
    return str(value)


_MISSING: Any = type("_Missing", (), {"__repr__": lambda self: "<missing>"})()


def _get(obj: Any, key: Union[str, int], data_key: str = "") -> Any:
    """``obj[key]`` / ``obj.key`` for models, mappings and lists, else _MISSING."""
    if obj is None or obj is _MISSING:
        return _MISSING
    if isinstance(key, int):
        try:
            return obj[key]
        except (IndexError, KeyError, TypeError):
            return _MISSING
    if isinstance(obj, Mapping):
        if key in obj:
            return obj[key]
        return obj[data_key] if data_key and data_key in obj else _MISSING
    return getattr(obj, key, _MISSING)


def _takes_arg(fn: Callable[..., Any]) -> bool:
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(
        p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        )
        for p in params
    )


def _root_page(page: Any) -> Any:
    while getattr(page, "_parent_page", None) is not None:
        page = page._parent_page
    return page


def _current_page() -> Any:
    from pywire.core.dispatch import _page_context
    from pywire.core.wire import _render_context

    ctx = _render_context.get()
    if ctx is not None:
        return ctx[0]
    return _page_context.get(None)


def _kebab(text: str) -> str:
    out = []
    for i, ch in enumerate(text):
        if ch.isupper() and i and (text[i - 1].islower() or text[i - 1].isdigit()):
            out.append("-")
        out.append(ch.lower() if ch.isalnum() else "-")
    return "".join(out).strip("-") or "form"


class FieldList:
    """Bound fields of a model, in model order.

    Iterate it to auto-render a form; reach one by name with attribute or
    item access (the way to reach a field whose name clashes with a
    ``Form`` or ``BoundField`` member).
    """

    def __init__(self, form: "Form[Any]", path: Path, spec: FieldSpec) -> None:
        self._form = form
        self._path = path
        self._spec = spec

    def __iter__(self) -> Iterator["BoundField[Any]"]:
        for key in self._spec.children:
            yield self._form._field(self._path + (key,))

    def __len__(self) -> int:
        return len(self._spec.children)

    def __getitem__(self, key: str) -> "BoundField[Any]":
        if key not in self._spec.children:
            raise KeyError(key)
        return self._form._field(self._path + (key,))

    def __getattr__(self, key: str) -> "BoundField[Any]":
        if key.startswith("_"):
            raise AttributeError(key)
        if key not in self._spec.children:
            raise AttributeError(self._form._no_field_message(self._spec, key))
        return self._form._field(self._path + (key,))


class BoundField(Generic[T]):
    """One model field bound to its form: value, errors and HTML attributes."""

    __slots__ = ("_form", "_path", "_spec")

    def __init__(self, form: "Form[Any]", path: Path, spec: FieldSpec) -> None:
        self._form = form
        self._path = path
        self._spec = spec

    if TYPE_CHECKING:
        # Typing aid for nested paths; see ``Form._pw_shape``.
        @property
        def _pw_shape(self) -> T: ...

    # -- identity ----------------------------------------------------------

    @property
    def html_name(self) -> str:
        """The HTML ``name``: dotted data keys, list rows by index."""
        return self._form._html_name(self._path)

    @property
    def html_id(self) -> str:
        return f"{self._form._dom_id_value()}-{self.html_name.replace('.', '-')}"

    @property
    def error_id(self) -> str:
        return f"{self.html_id}-error"

    @property
    def label(self) -> str:
        return self._spec.label

    @property
    def help(self) -> Optional[str]:
        """The model field's ``description``."""
        return self._spec.description

    @property
    def required(self) -> bool:
        return self._spec.required

    @property
    def options(self) -> Tuple[Option, ...]:
        return self._spec.options

    # -- state -------------------------------------------------------------

    @property
    def raw(self) -> Union[str, List[str]]:
        """What the user typed, as the browser sent it."""
        self._form._track()
        return self._form._display(self._path, self._spec)

    @property
    def value(self) -> Optional[T]:
        """The value as the model's type, when it parses; else None."""
        self._form._track()
        return self._form._typed_value(self._path, self._spec)

    @property
    def errors(self) -> List[FieldError]:
        """Current errors, once the field was filled in and left, or submitted."""
        self._form._track()
        key = self._form._path_key(self._path)
        if not self._form._shown(key):
            return []
        return list(self._form._errors.get(key, ()))

    @property
    def error(self) -> Optional[str]:
        errs = self.errors
        return errs[0].message if errs else None

    @error.setter
    def error(self, message: Optional[str]) -> None:
        self._form._set_error(self._form._path_key(self._path), message)

    @property
    def fields(self) -> FieldList:
        if self._spec.kind != "model":
            raise AttributeError(f"{self.html_name!r} has no sub-fields")
        return FieldList(self._form, self._path, self._spec)

    @property
    def attrs(self) -> Dict[str, str]:
        """The generated HTML attributes, e.g. to spread onto a component."""
        tag = "select" if self._spec.input_type == "select" else "input"
        if self._spec.kind == "multichoice":
            tag = "select"
        return self._pw_render_attrs(tag, {}, None)

    @property
    def add_button(self) -> Dict[str, Any]:
        """Attributes for a button that adds a row to this list field.

        ``<button {**signup.items.add_button}>Add item</button>``: a submit
        button, so what the user typed is kept, with or without JavaScript.
        """
        if self._spec.kind != "list":
            raise TypeError(f"{self.html_name!r} is not a list field")
        return _action_button(f"add:{self.html_name}")

    @property
    def remove_button(self) -> Dict[str, Any]:
        """Attributes for a button that removes this row from its list."""
        if not self._path or not isinstance(self._path[-1], int):
            raise TypeError(f"{self.html_name!r} is not a list row")
        return _action_button(f"remove:{self.html_name}")

    # -- nesting -----------------------------------------------------------

    def __getattr__(self, key: str) -> "BoundField[Any]":
        if key.startswith("_"):
            raise AttributeError(key)
        spec = object.__getattribute__(self, "_spec")
        if spec.kind == "model" and key in spec.children:
            return self._form._field(self._path + (key,))
        raise AttributeError(self._form._no_field_message(spec, key))

    def __getitem__(self, key: Union[int, str]) -> "BoundField[Any]":
        if isinstance(key, int) and self._spec.kind == "list":
            if key < 0:
                key += len(self)
            if key < 0:
                raise IndexError(key)
            return self._form._field(self._path + (key,))
        if isinstance(key, str) and self._spec.kind == "model":
            if key not in self._spec.children:
                raise KeyError(key)
            return self._form._field(self._path + (key,))
        raise TypeError(f"{self.html_name!r} does not support [{key!r}]")

    def __len__(self) -> int:
        if self._spec.kind != "list":
            raise TypeError(f"{self.html_name!r} is not a list field")
        self._form._track()
        return self._form._row_count(self._path, self._spec)

    def __iter__(self) -> Iterator["BoundField[Any]"]:
        if self._spec.kind != "list":
            raise TypeError(f"{self.html_name!r} is not a list field")
        for i in range(len(self)):
            yield self._form._field(self._path + (i,))

    def __str__(self) -> str:
        raw = self.raw
        return ", ".join(raw) if isinstance(raw, list) else raw

    def __repr__(self) -> str:
        return f"<BoundField {self.html_name!r} of {self._form.model.__name__}>"

    # -- rendering (used by $bind codegen) ---------------------------------

    def _pw_render_attrs(
        self, tag: str, hand: Mapping[str, Any], page: Any
    ) -> Dict[str, Any]:
        from pywire.forms.render import field_attrs

        return field_attrs(self, tag, dict(hand), page)


class Form(Generic[M]):
    """A form bound to a Pydantic model. Create one with ``form(Model)``."""

    _spec: FieldSpec

    def __init__(
        self,
        model: type[M],
        *,
        initial: Any = None,
        context: Union[Mapping[str, Any], Callable[[], Mapping[str, Any]], None] = None,
        messages: Optional[Messages] = None,
        id: Optional[str] = None,
        validate: Literal["blur", "submit"] = "blur",
    ) -> None:
        if not (isinstance(model, type) and issubclass(model, BaseModel)):
            raise TypeError(
                f"form() takes a Pydantic model class, got {model!r}. "
                "Define `class MyForm(BaseModel): ...` and pass MyForm."
            )
        if validate not in ("blur", "submit"):
            raise ValueError(f"validate={validate!r}: use 'blur' or 'submit'")
        object.__setattr__(self, "_spec", root_spec(model))
        self.model = model
        self._live = validate == "blur"
        self._initial = initial
        self._context = context
        self._messages: Dict[str, Any] = dict(messages or {})
        self._dom_id: Optional[str] = id
        self._rev = WirePrimitive(0)
        self._raw: Flat = {}
        self._has_raw = False
        self._errors: Dict[str, List[FieldError]] = {}
        self._value: Optional[M] = None
        self._submitted = False
        # Fields the user has been through (path keys): their errors show
        # before the form is submitted.
        self._touched: set[str] = set()
        self._owned: set[str] = set()
        # Row counts from add/remove buttons, by list HTML name.
        self._rows: Dict[str, int] = {}
        self._focus_claimed = False
        self._cache: Dict[Path, BoundField[Any]] = {}
        self._adapters: Dict[int, TypeAdapter[Any]] = {}

    # -- typing aids -------------------------------------------------------
    # The language server rewrites ``signup.email`` to
    # ``signup._pw_field(signup._pw_shape.email)``, and each further step
    # the same way (``signup._pw_field(<step>._pw_shape.street)``), so ty
    # checks field paths against the model and knows each field's type.
    # ``_pw_field`` drops ``None`` so optional sub-models keep their fields.
    # Neither exists at runtime.
    if TYPE_CHECKING:

        @property
        def _pw_shape(self) -> M: ...

        def _pw_field(self, value: Optional[T], /) -> BoundField[T]: ...

        def __getattr__(self, name: str) -> BoundField[Any]: ...

    else:

        def __getattr__(self, name: str) -> BoundField[Any]:
            if name.startswith("_"):
                raise AttributeError(name)
            spec = object.__getattribute__(self, "_spec")
            if name in spec.children:
                return self._field((name,))
            raise AttributeError(self._no_field_message(spec, name))

    def __setattr__(self, name: str, value: Any) -> None:
        spec = self.__dict__.get("_spec")
        if spec is not None and not name.startswith("_") and name in spec.children:
            raise AttributeError(
                f"Can't assign to form field {name!r}. Set values with "
                "form.load(...) or form(Model, initial=...), and errors with "
                f"form.{name}.error = '...'"
            )
        object.__setattr__(self, name, value)

    def __getitem__(self, name: str) -> BoundField[Any]:
        if name not in self._spec.children:
            raise KeyError(name)
        return self._field((name,))

    def __repr__(self) -> str:
        return f"<Form {self.model.__name__}>"

    # -- public state ------------------------------------------------------

    @property
    def fields(self) -> FieldList:
        return FieldList(self, (), self._spec)

    @property
    def value(self) -> Optional[M]:
        """The last valid model instance from a submit, or None."""
        self._track()
        return self._value

    @property
    def valid(self) -> bool:
        """True when the last check (live or submit) found no errors."""
        self._track()
        return not self._errors

    @property
    def submitted(self) -> bool:
        self._track()
        return self._submitted

    @property
    def dirty(self) -> bool:
        """True when what was submitted differs from the initial values."""
        self._track()
        if not self._has_raw:
            return False
        for name, values in self._raw.items():
            path, spec = self._lookup(name)
            if spec is None or _is_secret(spec):
                continue
            initial = self._initial_display(path, spec)
            shown = values if spec.multiple else (values[-1] if values else "")
            if shown != initial:
                return True
        return False

    @property
    def error(self) -> Optional[str]:
        """Form-level error: model validators, or one the handler sets."""
        self._track()
        errs = self._errors.get("") if self._submitted else None
        return errs[0].message if errs else None

    @error.setter
    def error(self, message: Optional[str]) -> None:
        self._set_error("", message)

    @property
    def errors(self) -> Dict[str, str]:
        """Every field error as ``{dotted path: message}``."""
        self._track()
        return {
            k: v[0].message
            for k, v in self._errors.items()
            if k and v and self._shown(k)
        }

    def load(self, obj: Any) -> None:
        """Fill the form from a model instance or mapping (edit forms)."""
        self._initial = obj
        self.reset()

    def reset(self) -> None:
        """Back to the initial values, with no errors."""
        self._raw = {}
        self._has_raw = False
        self._errors = {}
        self._value = None
        self._submitted = False
        self._touched = set()
        self._rows = {}
        self._touch()

    # -- snapshot hooks (session_serializer) --------------------------------

    def __pw_snapshot__(self) -> Dict[str, Any]:
        return {
            "raw": {
                k: [v for v in vs if isinstance(v, str)] for k, vs in self._raw.items()
            },
            "has_raw": self._has_raw,
            "errors": {k: [e.to_dict() for e in v] for k, v in self._errors.items()},
            "submitted": self._submitted,
            "touched": sorted(self._touched),
            "owned": sorted(self._owned),
            "rows": dict(self._rows),
        }

    def __pw_restore__(self, state: Mapping[str, Any]) -> None:
        if not isinstance(state, Mapping):
            return
        raw_state = state.get("raw")
        errors_state = state.get("errors")
        raw: Flat = {}
        for name, values in (
            raw_state if isinstance(raw_state, Mapping) else {}
        ).items():
            _, spec = self._lookup(str(name))
            if spec is None or _is_secret(spec) or not isinstance(values, list):
                continue
            raw[str(name)] = [v for v in values if isinstance(v, str)]
        self._raw = raw
        self._has_raw = bool(state.get("has_raw"))
        self._errors = {
            str(k): [FieldError.from_dict(e) for e in v if isinstance(e, Mapping)]
            for k, v in (
                errors_state if isinstance(errors_state, Mapping) else {}
            ).items()
            if isinstance(v, list)
        }
        self._submitted = bool(state.get("submitted"))
        touched = state.get("touched")
        self._touched = (
            {t for t in touched if isinstance(t, str)}
            if isinstance(touched, list)
            else set()
        )
        owned = state.get("owned")
        self._owned = (
            {n for n in owned if isinstance(n, str)}
            if isinstance(owned, list)
            else set()
        )
        rows = state.get("rows")
        self._rows = {
            str(k): v
            for k, v in (rows if isinstance(rows, Mapping) else {}).items()
            if isinstance(v, int) and 0 <= v <= MAX_ROWS
        }
        self._touch()

    def _pw_hidden_inputs(self) -> str:
        """HTML for state the form posts back (see ``Wizard``)."""
        return ""

    # -- the pipeline ------------------------------------------------------

    async def _pw_submit(self, page: Any, handler: Any, event: Any) -> None:
        """Whitelist, shape, validate, then call the handler with the model.

        Generated for ``<form $bind={f} @submit={handler}>``: the only way a
        client reaches ``handler``, which never sees unvalidated data.
        """
        form_data = _event_value(event, "formData")
        flat = normalize(form_data if isinstance(form_data, Mapping) else {})
        action = _pop_action(flat)
        self._capture(flat)
        if action is not None:
            self._apply_action(action)
            return
        data = shape(self._spec, self._with_owned(flat))
        if _event_value(event, "type") == "validate":
            self._validate_live(data, _event_value(event, "field"))
            return
        self._submitted = True
        instance = self._validate(data)
        self._touch()
        if instance is None:
            _mark_invalid(page)
            return
        if handler is not None:
            result = handler(instance) if _takes_arg(handler) else handler()
            if inspect.isawaitable(result):
                await result
        if self._errors:
            _mark_invalid(page)

    def _validate_live(self, data: Dict[str, Any], field: Any) -> None:
        """A field was left (or changed): check the whole form, show its errors."""
        if not self._live:
            return
        if isinstance(field, str):
            path, _ = self._lookup(field)
            if path:
                self._touched.add(self._path_key(path))
        value = self._value
        self._validate(data)
        self._value = value  # .value is the last *submitted* valid model
        self._touch()

    def _apply_action(self, action: str) -> None:
        """Add or remove a list row, keeping what the user typed."""
        verb, _, name = action.partition(":")
        if verb == "add":
            path = self._list_path(name)
            if path is None:
                return
            spec = self._spec_at(path)
            count = self._row_count(path, spec)
            if count < min(spec.max_items or MAX_ROWS, MAX_ROWS):
                self._rows[name] = count + 1
        elif verb == "remove":
            list_name, _, index = name.rpartition(".")
            path = self._list_path(list_name)
            if path is None or not index.isdigit():
                return
            count = self._row_count(path, self._spec_at(path))
            row = int(index)
            if row >= count:
                return
            html = _shift_rows(list_name + ".", row)
            self._raw = {
                new: v for k, v in self._raw.items() if (new := html(k)) is not None
            }
            key = _shift_rows(self._path_key(path) + ".", row)
            self._errors = {
                new: v for k, v in self._errors.items() if (new := key(k)) is not None
            }
            self._touched = {new for t in self._touched if (new := key(t)) is not None}
            self._rows[list_name] = count - 1
        self._touch()

    def _list_path(self, name: str) -> Optional[Path]:
        path, spec = self._lookup(name)
        if spec is None and path and self._spec_at(path).kind == "list":
            return path
        return None

    def _shown(self, key: str) -> bool:
        """Errors show after a submit, or for fields the user has been through."""
        if self._submitted:
            return True
        if not key:
            return False
        prefix = key + "."
        return any(t == key or t.startswith(prefix) for t in self._touched)

    def _validate(self, data: Dict[str, Any]) -> Optional[M]:
        ctx = self._context
        if ctx is not None and not isinstance(ctx, Mapping):
            ctx = ctx()
        try:
            instance = self.model.model_validate(data, context=ctx)
        except ValidationError as exc:
            errors: Dict[str, List[FieldError]] = {}
            for err in exc.errors(include_url=False):
                path, spec = error_path(self._spec, tuple(err.get("loc", ())))
                errors.setdefault(path, []).append(
                    map_error(err, spec, self._messages, path)
                )
            self._errors = errors
            self._value = None
            return None
        self._errors = {}
        self._value = instance
        return instance

    def _capture(self, flat: Flat) -> None:
        """Keep what the user typed (schema names only, never secrets)."""
        raw: Flat = {}
        for name, values in flat.items():
            _, spec = self._lookup(name)
            if spec is None or _is_secret(spec) or spec.kind in ("file", "files"):
                continue
            raw[name] = [v for v in values if isinstance(v, str)]
        self._raw = raw
        self._has_raw = True

    def _with_owned(self, flat: Flat) -> Flat:
        """Fields rendered disabled/readonly keep their server value."""
        if not self._owned:
            return flat
        flat = dict(flat)
        for name in self._owned:
            path, spec = self._lookup(name)
            if spec is None:
                continue
            initial = self._initial_display(path, spec)
            flat[name] = list(initial) if isinstance(initial, list) else [initial]
            if spec.kind == "boolean" and initial == "":
                flat.pop(name)
        return flat

    # -- internals ---------------------------------------------------------

    def _track(self) -> None:
        self._rev.value  # noqa: B018  (registers the read with the render)

    def _touch(self) -> None:
        self._rev.value = self._rev.peek() + 1

    def _set_error(self, key: str, message: Optional[str]) -> None:
        if message:
            self._errors[key] = [FieldError(code="customError", message=str(message))]
            if key:
                self._touched.add(key)
        else:
            self._errors.pop(key, None)
        self._touch()

    def _field(self, path: Path) -> BoundField[Any]:
        field = self._cache.get(path)
        if field is None:
            spec = self._spec_at(path)
            field = self._cache[path] = BoundField(self, path, spec)
        return field

    def _spec_at(self, path: Path) -> FieldSpec:
        spec = self._spec
        for key in path:
            if isinstance(key, int):
                assert spec.item is not None
                spec = spec.item
            else:
                spec = spec.children[key]
        return spec

    def _lookup(self, name: str) -> Tuple[Path, Optional[FieldSpec]]:
        """HTML name -> (python path, spec), or (…, None) if not in schema."""
        spec: Optional[FieldSpec] = self._spec
        path: List[Union[str, int]] = []
        for part in name.split("."):
            if spec is None:
                return (), None
            if spec.kind == "list" and part.isdigit() and len(part) <= 6:
                path.append(int(part))
                spec = spec.item
            elif spec.kind == "model":
                child = next(
                    (c for c in spec.children.values() if c.data_key == part), None
                )
                if child is None:
                    return (), None
                path.append(child.key)
                spec = child
            else:
                return (), None
        if spec is None or spec.kind in ("model", "list"):
            return tuple(path), None
        return tuple(path), spec

    def _html_name(self, path: Path) -> str:
        spec = self._spec
        parts: List[str] = []
        for key in path:
            if isinstance(key, int):
                parts.append(str(key))
                assert spec.item is not None
                spec = spec.item
            else:
                spec = spec.children[key]
                parts.append(spec.data_key)
        return ".".join(parts)

    def _path_key(self, path: Path) -> str:
        return ".".join(str(p) for p in path)

    def _dom_id_value(self) -> str:
        if self._dom_id:
            return self._dom_id
        page = _current_page()
        if page is not None:
            for attr, value in vars(page).items():
                if value is self and not attr.startswith("_"):
                    key = getattr(page, "_component_key", None)
                    prefix = f"{_kebab(str(key))}-" if key else ""
                    self._dom_id = f"{prefix}{_kebab(attr)}"
                    return self._dom_id
        return _kebab(self.model.__name__)

    def _no_field_message(self, spec: FieldSpec, name: str) -> str:
        model = spec.model.model.__name__ if spec.model is not None else "field"
        close = difflib.get_close_matches(name, list(spec.children), n=1)
        hint = f" Did you mean {close[0]!r}?" if close else ""
        return f"{model} has no field {name!r}.{hint}"

    def _initial_value(self, path: Path) -> Any:
        obj: Any = self._initial
        spec = self._spec
        for key in path:
            if isinstance(key, int):
                assert spec.item is not None
                spec = spec.item
                obj = _get(obj, key)
            else:
                spec = spec.children[key]
                obj = _get(obj, key, spec.data_key)
        if obj is _MISSING:
            return spec.default if spec.has_default else None
        return obj

    def _initial_display(self, path: Path, spec: FieldSpec) -> Union[str, List[str]]:
        if _is_secret(spec):
            return ""
        value = self._initial_value(path)
        if spec.multiple:
            if value is None:
                return []
            return [_to_html(v) for v in value]
        return _to_html(value)

    def _display(self, path: Path, spec: FieldSpec) -> Union[str, List[str]]:
        if _is_secret(spec) or spec.kind in ("file", "files"):
            return [] if spec.multiple else ""
        name = self._html_name(path)
        if name in self._raw:
            values = self._raw[name]
            return list(values) if spec.multiple else (values[-1] if values else "")
        if (
            self._has_raw
            and name not in self._owned
            and (spec.multiple or spec.kind == "boolean")
        ):
            # Submitted without it: nothing ticked.
            return [] if spec.multiple else ""
        return self._initial_display(path, spec)

    def _typed_value(self, path: Path, spec: FieldSpec) -> Any:
        if self._value is not None:
            obj: Any = self._value
            for key in path:
                obj = _get(obj, key)
            return None if obj is _MISSING else obj
        if not self._has_raw:
            return self._initial_value(path)
        raw = self._display(path, spec)
        if raw == "" and spec.kind not in ("boolean",):
            return None
        annotation = self._annotation_at(path)
        if annotation is None:
            return raw
        adapter = self._adapters.get(id(spec))
        if adapter is None:
            adapter = self._adapters[id(spec)] = TypeAdapter(annotation)
        try:
            if spec.kind == "boolean":
                return adapter.validate_python(raw == "true" or raw == "on")
            return adapter.validate_python(raw)
        except ValidationError:
            return None

    def _annotation_at(self, path: Path) -> Any:
        model: Optional[type[BaseModel]] = self.model
        annotation: Any = None
        from pywire.forms.schema import _item_annotation, _model_class

        for key in path:
            if isinstance(key, int):
                annotation = _item_annotation(annotation)
                model = _model_class(annotation) if annotation is not None else None
                continue
            if model is None:
                return None
            info = model.model_fields.get(key)
            if info is None:
                return None
            annotation = info.annotation
            model = _model_class(annotation)
        return annotation

    def _row_count(self, path: Path, spec: FieldSpec) -> int:
        name = self._html_name(path)
        prefix = name + "."
        rows = {
            int(k[len(prefix) :].split(".", 1)[0])
            for k in self._raw
            if k.startswith(prefix) and k[len(prefix) :].split(".", 1)[0].isdigit()
        }
        from_raw = max(rows) + 1 if rows else 0
        initial = self._initial_value(path)
        from_initial = len(initial) if isinstance(initial, (list, tuple)) else 0
        count = from_raw if self._has_raw else max(from_raw, from_initial)
        # A row whose inputs send nothing (unticked boxes) still counts.
        return max(count, self._rows.get(name, 0))


def _event_value(event: Any, key: str) -> Any:
    """``event.<key>`` for event objects, ``event[key]`` for plain mappings."""
    if isinstance(event, Mapping):
        return event.get(key)
    raw = getattr(event, "_raw_data", None)
    if isinstance(raw, Mapping):
        return raw.get(key)
    return None


def _action_button(value: str) -> Dict[str, Any]:
    return {
        "type": "submit",
        "name": ACTION,
        "value": value,
        "formnovalidate": True,
    }


def _pop_action(flat: Flat) -> Optional[str]:
    values = flat.pop(ACTION, None)
    last = values[-1] if values else None
    return last if isinstance(last, str) else None


def _shift_rows(prefix: str, removed: int) -> Callable[[str], Optional[str]]:
    """Rename keys under ``prefix`` as if row ``removed`` were deleted."""

    def shift(key: str) -> Optional[str]:
        if not key.startswith(prefix):
            return key
        head, dot, rest = key[len(prefix) :].partition(".")
        if not head.isdigit():
            return key
        row = int(head)
        if row == removed:
            return None
        if row < removed:
            return key
        return f"{prefix}{row - 1}{dot}{rest}"

    return shift


def _mark_invalid(page: Any) -> None:
    if page is not None:
        _root_page(page)._pw_form_invalid = True


def form(
    model: type[M],
    /,
    *,
    initial: Any = None,
    context: Union[Mapping[str, Any], Callable[[], Mapping[str, Any]], None] = None,
    messages: Optional[Messages] = None,
    id: Optional[str] = None,
    validate: Literal["blur", "submit"] = "blur",
) -> Form[M]:
    """Bind a Pydantic model to a ``<form $bind={...}>``.

    Args:
        model: The model that defines the fields and every rule.
        initial: A model instance or mapping to prefill (edit forms).
        context: Passed to ``model_validate(context=...)``, or a callable
            returning it, for rules that depend on server state.
        messages: Override error messages by code (``"tooShort"``) or by
            field and code (``"name.tooShort"``). ``{min_length}`` style
            placeholders are filled from the error.
        id: DOM id prefix. Defaults to the variable name on the page.
        validate: ``"blur"`` (default) checks a field when the user leaves
            it, then as they type while it shows an error; ``"submit"``
            checks on submit only.
    """
    return Form(
        model,
        initial=initial,
        context=context,
        messages=messages,
        id=id,
        validate=validate,
    )
