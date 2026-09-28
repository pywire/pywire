"""HTML attributes for ``$bind`` (called from generated render code).

The model writes the attributes that carry meaning (name, type, the
constraints, the value); attributes written by hand keep the presentation
(class, placeholder, autocomplete ...). A hand-written constraint that
disagrees with the model is an error in dev mode, because the server would
never enforce it; in production the model's value wins and a warning is
logged.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Dict, List, Mapping

from pywire.runtime.bind import BindError
from pywire.runtime.escape import escape_html

if TYPE_CHECKING:
    from pywire.forms.form import BoundField

logger = logging.getLogger(__name__)

CONSTRAINTS = frozenset(
    {"required", "minlength", "maxlength", "min", "max", "step", "pattern", "multiple"}
)
BOOLEAN_CONSTRAINTS = frozenset({"required", "multiple"})
TEXT_TYPES = frozenset({"text", "email", "url", "tel", "search", "password"})
_TYPES_FOR_KIND: Dict[str, frozenset] = {
    "text": TEXT_TYPES | {"hidden"},
    "secret": TEXT_TYPES | {"hidden"},
    "integer": frozenset({"number", "range", "text", "hidden"}),
    "number": frozenset({"number", "range", "text", "hidden"}),
    "boolean": frozenset({"checkbox", "radio", "hidden"}),
    "choice": frozenset({"radio", "text", "search", "hidden"}),
    "multichoice": frozenset({"checkbox", "hidden"}),
    "multi": TEXT_TYPES | {"number", "checkbox", "date", "hidden"},
    "date": frozenset({"date", "text", "hidden"}),
    "datetime": frozenset({"datetime-local", "text", "hidden"}),
    "time": frozenset({"time", "text", "hidden"}),
    "file": frozenset({"file"}),
    "files": frozenset({"file"}),
}
# Which constraint attributes apply to which input types.
_APPLIES = {
    "minlength": TEXT_TYPES,
    "maxlength": TEXT_TYPES,
    "pattern": TEXT_TYPES,
    "min": frozenset({"number", "range", "date", "datetime-local", "time"}),
    "max": frozenset({"number", "range", "date", "datetime-local", "time"}),
    "step": frozenset({"number", "range", "date", "datetime-local", "time"}),
    "inputmode": frozenset({"number", "text"}),
}


def _is_debug(page: Any) -> bool:
    check = getattr(page, "_is_debug", None)
    try:
        return bool(check()) if callable(check) else False
    except Exception:
        return False


def _complain(page: Any, message: str) -> None:
    if _is_debug(page):
        raise BindError(message)
    logger.warning(message)


def _root(page: Any) -> Any:
    while getattr(page, "_parent_page", None) is not None:
        page = page._parent_page
    return page


def _require_field(obj: Any, tag: str) -> "BoundField[Any]":
    from pywire.forms.form import BoundField, Form

    if isinstance(obj, BoundField):
        return obj
    if isinstance(obj, Form):
        raise BindError(
            f"$bind on <{tag}> needs a field like form.email, not the whole "
            "form. Bind the form itself on the <form> element."
        )
    raise BindError(
        f"$bind on <{tag}> expects a form field (e.g. signup.email), got "
        f"{type(obj).__name__} {obj!r}."
    )


def _present(attrs: Mapping[str, Any], key: str) -> bool:
    return key in attrs and attrs[key] is not None and attrs[key] is not False


def _merge(
    page: Any, field: "BoundField[Any]", base: Dict[str, Any], hand: Dict[str, Any]
) -> Dict[str, Any]:
    """Hand-written attributes on top of the model's, constraints excepted."""
    out = dict(hand)
    for key in CONSTRAINTS:
        if not _present(hand, key):
            continue
        if key not in base:
            if _is_debug(page):
                logger.warning(
                    "%s: %s in the template has no rule in the model behind it, "
                    "so only the browser checks it.",
                    field.html_name,
                    key,
                )
            continue
        same = key in BOOLEAN_CONSTRAINTS or str(hand[key]) == str(base[key])
        if not same:
            _complain(
                page,
                f"{field.html_name}: {key}={hand[key]!r} in the template disagrees "
                f"with the model ({key}={base[key]!r}). The server enforces the "
                "model; change the model instead.",
            )
    for key, value in base.items():
        if key == "id" and _present(hand, "id"):
            continue
        out[key] = value
    return out


def field_attrs(
    field: Any, tag: str, hand: Dict[str, Any], page: Any
) -> Dict[str, Any]:
    field = _require_field(field, tag)
    spec = field._spec
    kind = spec.kind
    if kind in ("model", "list"):
        example = next(iter(spec.children), "field") if kind == "model" else "0"
        raise BindError(
            f"$bind on <{tag}>: {field.html_name!r} is a group of fields. Bind "
            f"each one instead, e.g. {field.html_name}.{example}."
        )
    if "name" in hand and str(hand["name"]) != field.html_name:
        _complain(
            page,
            f"$bind sets name={field.html_name!r}; the template's name="
            f"{hand['name']!r} would post a field the server ignores.",
        )

    form = field._form
    if page is not None and (_present(hand, "disabled") or _present(hand, "readonly")):
        # Rendered read-only: the value comes from server state on submit.
        form._owned.add(field.html_name)

    base: Dict[str, Any] = {"name": field.html_name, "id": field.html_id}
    display = field.raw

    if tag == "select":
        if spec.required:
            base["required"] = True
        if spec.multiple:
            base["multiple"] = True
    elif tag == "textarea":
        if spec.required:
            base["required"] = True
        for key in ("minlength", "maxlength"):
            if key in spec.attrs:
                base[key] = spec.attrs[key]
    else:
        itype = _input_type(page, field, hand.get("type"))
        base["type"] = itype
        if itype in ("checkbox", "radio"):
            option = _option_value(page, field, itype, hand)
            base["value"] = option
            if itype == "radio" or kind != "boolean":
                # One input per option: each needs its own id.
                base["id"] = field.html_id + "-" + re.sub(r"\s+", "-", option)
            chosen = display if isinstance(display, list) else [display]
            if option in chosen:
                base["checked"] = True
            else:
                hand = {k: v for k, v in hand.items() if k != "checked"}
            if spec.required and (itype == "radio" or kind == "boolean"):
                base["required"] = True
        elif itype == "file":
            if spec.kind == "files":
                base["multiple"] = True
                if spec.max_items is not None:
                    base["data-pw-max-files"] = str(spec.max_items)
            if spec.required:
                base["required"] = True
            # accept= and data-pw-max-size, from UploadField: the client
            # checks them before uploading.
            base.update(spec.attrs)
            if page is not None:
                _root(page)._pw_has_uploads = True
        else:
            if itype == "password" and kind != "secret":
                _complain(
                    page,
                    f'{field.html_name}: type="password" on a plain str field. '
                    "Type it SecretStr so its value is never echoed back, kept in "
                    "a snapshot or carried between wizard steps.",
                )
            if spec.required:
                base["required"] = True
            for key, value in spec.attrs.items():
                if itype in _APPLIES.get(key, frozenset()):
                    base[key] = value
            if "value" in hand and itype != "hidden":
                _complain(
                    page,
                    f"<input $bind={{…{field.html_name}}}> has value= in the template; "
                    "a bound field's value comes from the form. Prefill it with "
                    "form(Model, initial=...) or form.load(...).",
                )
            if itype != "password":
                base["value"] = display if isinstance(display, str) else ""

    if field.errors:
        base["aria-invalid"] = "true"
        described = str(hand.get("aria-describedby", "")).split()
        if field.error_id not in described:
            described.append(field.error_id)
        base["aria-describedby"] = " ".join(described)
        if form._submitted and not form._focus_claimed:
            # After a submit without JS the browser lands on the first
            # invalid field; with JS the client moves focus itself.
            form._focus_claimed = True
            base["autofocus"] = True

    return _merge(page, field, base, hand)


def _input_type(page: Any, field: "BoundField[Any]", hand_type: Any) -> str:
    spec = field._spec
    allowed = _TYPES_FOR_KIND.get(spec.kind, TEXT_TYPES)
    if hand_type is None:
        if spec.kind == "choice":
            raise BindError(
                f"{field.html_name!r} is a choice. Bind it on a <select>, or on "
                '<input type="radio" value="..."> for each option.'
            )
        if spec.kind == "multichoice":
            raise BindError(
                f"{field.html_name!r} takes several choices. Bind it on a <select>, "
                'or on <input type="checkbox" value="..."> for each option.'
            )
        if spec.kind == "multi":
            return spec.item.input_type if spec.item is not None else "text"
        return spec.input_type
    hand_type = str(hand_type).lower()
    if hand_type not in allowed:
        _complain(
            page,
            f'type="{hand_type}" can\'t hold {field.html_name!r} ({spec.kind}); '
            f"use one of: {', '.join(sorted(allowed))}.",
        )
        return spec.input_type
    return hand_type


def _option_value(
    page: Any, field: "BoundField[Any]", itype: str, hand: Mapping[str, Any]
) -> str:
    spec = field._spec
    if spec.kind == "boolean":
        if itype == "checkbox":
            return "true"
        return str(hand.get("value", "true"))
    if "value" not in hand:
        raise BindError(
            f'<input type="{itype}" $bind={{…{field.html_name}}}> needs a value= '
            "naming the option it stands for."
        )
    value = str(hand["value"])
    if spec.options and value not in {o.value for o in spec.options}:
        _complain(
            page,
            f"value={value!r} is not an option of {field.html_name!r} "
            f"({', '.join(o.value for o in spec.options)}).",
        )
    return value


def form_attrs(
    form: Any, handler_name: str, hand: Dict[str, Any], page: Any
) -> Dict[str, Any]:
    from pywire.forms.form import Form

    if not isinstance(form, Form):
        raise BindError(
            "$bind on <form> expects a form from form(Model), got "
            f"{type(form).__name__} {form!r}."
        )
    method = str(hand.get("method", "post")).lower()
    if method != "post":
        _complain(page, "A bound form always posts; drop method= from the <form>.")
    # Fields re-register as they render: only what renders read-only now is
    # server-owned on the next submit.
    form._owned.clear()
    form._focus_claimed = False
    base: Dict[str, Any] = {"method": "post", "data-pw-form": form._dom_id_value()}
    if form._live:
        base["data-pw-validate"] = "blur"
    if "id" not in hand:
        base["id"] = form._dom_id_value()
    if _has_files(form._spec):
        base["enctype"] = "multipart/form-data"
        if page is not None:
            _root(page)._pw_has_uploads = True
    out = dict(hand)
    out.update(base)
    return out


def _has_files(spec: Any, depth: int = 0) -> bool:
    if depth > 8:
        return False
    for child in spec.children.values():
        if child.kind in ("file", "files"):
            return True
        if child.kind == "model" and _has_files(child, depth + 1):
            return True
        if child.kind == "list" and child.item and _has_files(child.item, depth + 1):
            return True
    return False


def handler_input(form: Any, handler_name: str) -> str:
    """Hidden inputs a bound form posts: its handler, and any form state.

    ``form_attrs`` has already checked that ``form`` is a Form.
    """
    hidden = form._pw_hidden_inputs()
    return (
        '<input type="hidden" name="__pywire_handler" value="'
        f'{escape_html(handler_name)}">{hidden}'
    )


def textarea_text(field: Any) -> str:
    field = _require_field(field, "textarea")
    raw = field.raw
    return escape_html(raw if isinstance(raw, str) else "\n".join(raw))


def select_options(field: Any) -> str:
    """``<option>``s for a bound ``<select>`` written without any."""
    field = _require_field(field, "select")
    spec = field._spec
    options = spec.options or (spec.item.options if spec.item is not None else ())
    raw = field.raw
    chosen: List[str] = raw if isinstance(raw, list) else [raw]
    parts: List[str] = []
    if not spec.multiple and (
        spec.nullable or not raw or raw not in [o.value for o in options]
    ):
        label = "Choose…" if spec.required else ""
        parts.append(f'<option value="">{escape_html(label)}</option>')
    for option in options:
        selected = " selected" if option.value in chosen else ""
        parts.append(
            f'<option value="{escape_html(option.value)}"{selected}>'
            f"{escape_html(option.label)}</option>"
        )
    return "".join(parts)
