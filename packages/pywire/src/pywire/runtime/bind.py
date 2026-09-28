"""``$bind`` on ``<input>``, ``<select>`` and ``<textarea>`` (render helpers).

``$bind`` means "this element's value is that". The target is either a form
field (``signup.email``, handled by :mod:`pywire.forms.render`) or a plain
wire defined in the frontmatter (``term = wire("")``), which this module
binds both ways: the element renders the wire's value, and editing the
element writes the wire, coerced to the type the wire holds.

Wire binding needs no Pydantic, so this module only imports the forms
package when a form field is bound.
"""

from __future__ import annotations

import decimal
from typing import Any, Dict, List, Mapping, Optional

from pywire.core.wire import WireBase, WireList, WireSet
from pywire.runtime.escape import escape_html

TEXT_TYPES = frozenset({"text", "email", "url", "tel", "search", "password"})
# Event fields a wire binding reads; the client sends nothing else.
_FIELD_MASK = "value,checked,values,inputType"


class BindError(TypeError):
    """A ``$bind`` that can't mean what it says."""


def _is_wire(obj: Any) -> bool:
    return isinstance(obj, WireBase)


def _current(wire: WireBase) -> Any:
    wire._track_read()
    return wire.peek()


def _is_many(value: Any) -> bool:
    return isinstance(value, (list, set, tuple, frozenset))


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else ""
    return str(value)


def field_attrs(
    obj: Any, tag: str, hand: Dict[str, Any], page: Any, handler: str = ""
) -> Dict[str, Any]:
    """Attributes for a bound ``<input>``/``<select>``/``<textarea>``."""
    if not _is_wire(obj):
        from pywire.forms.render import field_attrs as form_field_attrs

        return form_field_attrs(obj, tag, hand, page)
    if not handler:
        raise BindError(
            f"$bind on <{tag}> binds a wire defined in this page's frontmatter "
            '(e.g. term = wire("")) by its name, or a form field.'
        )
    current = _current(obj)
    out = dict(hand)
    if tag == "textarea":
        event = "input"
    elif tag == "select":
        event = "change"
        if _is_many(current):
            out["multiple"] = True
    else:
        event = _wire_input(out, current)

    if f"data-on-{event}" in hand:
        raise BindError(
            f"<{tag}> has $bind and @{event}: the binding already handles "
            f"{event}. Read the wire in code instead, or use another event."
        )
    out[f"data-on-{event}"] = handler
    out[f"data-pw-fields-{event}"] = _FIELD_MASK
    return out


def _wire_input(out: Dict[str, Any], current: Any) -> str:
    """Fill ``out`` for a bound ``<input>``; return the event it sends on."""
    hand_type = out.get("type")
    itype = str(hand_type).lower() if hand_type is not None else None
    if itype is None:
        if isinstance(current, bool):
            itype = "checkbox"
        elif isinstance(current, (int, float, decimal.Decimal)):
            itype = "number"
        elif _is_many(current):
            raise BindError(
                "$bind on <input> to a list wire needs "
                '<input type="checkbox" value="..."> for each choice, or a '
                "<select multiple>."
            )
        else:
            itype = "text"
        out["type"] = itype

    if itype == "file":
        raise BindError(
            "$bind can't hold files in a wire; bind a form field typed Upload."
        )
    if itype in ("checkbox", "radio"):
        if isinstance(current, bool) and itype == "checkbox":
            chosen = current
        else:
            if "value" not in out:
                raise BindError(
                    f'<input type="{itype}"> bound to a wire needs a value= '
                    "naming the choice it stands for."
                )
            option = str(out["value"])
            if _is_many(current):
                chosen = option in {_text(v) for v in current}
            else:
                chosen = _text(current) == option
        if chosen:
            out["checked"] = True
        else:
            out.pop("checked", None)
        return "change"

    if "value" in out:
        raise BindError(
            "<input> has $bind and value=: the wire is the value. Set the wire instead."
        )
    out["value"] = _text(current)
    if itype in TEXT_TYPES or itype == "number":
        return "input"
    return "change"


def textarea_text(obj: Any) -> str:
    if not _is_wire(obj):
        from pywire.forms.render import textarea_text as form_textarea_text

        return form_textarea_text(obj)
    return escape_html(_text(_current(obj)))


def select_options(obj: Any) -> str:
    """``<option>``s for a bound ``<select>`` written without any."""
    if not _is_wire(obj):
        from pywire.forms.render import select_options as form_select_options

        return form_select_options(obj)
    raise BindError(
        "A <select> bound to a wire needs its <option>s written out; only a "
        "form field knows its choices."
    )


def bind_select(page: Any, site: str, obj: Any) -> None:
    """Remember what a bound ``<select>`` holds, for its options."""
    selects: Optional[Dict[str, Any]] = getattr(page, "_pw_bound_selects", None)
    if selects is None:
        selects = page._pw_bound_selects = {}
    selects[site] = obj


def option_attrs(page: Any, site: str, attrs: Dict[str, Any]) -> Dict[str, Any]:
    """Mark a hand-written ``<option>`` selected when the binding holds it."""
    obj = (getattr(page, "_pw_bound_selects", None) or {}).get(site)
    if obj is None or "value" not in attrs:
        return attrs
    if _is_wire(obj):
        current = _current(obj)
        values = current if _is_many(current) else [current]
        chosen: List[str] = [_text(v) for v in values]
    else:
        raw = obj.raw
        chosen = raw if isinstance(raw, list) else [raw]
    out = dict(attrs)
    if str(attrs["value"]) in chosen:
        out["selected"] = True
    else:
        out.pop("selected", None)
    return out


def apply_bind_event(target: Any, event: Mapping[str, Any]) -> None:
    """Write what the user entered into a bound wire (generated handlers).

    The value is coerced to the type the wire holds. A number box that
    doesn't hold a number leaves the wire as it was.
    """
    if not _is_wire(target) or not isinstance(event, Mapping):
        return
    value = event.get("value")
    checked = event.get("checked")
    values = event.get("values")
    current = target.peek()

    if isinstance(target, (WireList, WireSet)):
        if isinstance(values, list):
            picked = [v for v in values if isinstance(v, str)]
        elif isinstance(checked, bool) and isinstance(value, str):
            picked = [_text(v) for v in current if _text(v) != value]
            if checked:
                picked.append(value)
        else:
            return
        target.value = set(picked) if isinstance(target, WireSet) else picked
        return

    if isinstance(current, bool):
        if isinstance(checked, bool) and event.get("inputType") != "radio":
            target.value = checked
        elif isinstance(value, str) and checked:
            target.value = value == "true"
        return
    if not isinstance(value, str):
        return
    if checked is False and event.get("inputType") == "radio":
        return
    coerced = _coerce(current, value)
    if coerced is not _UNCHANGED:
        target.value = coerced


_UNCHANGED: Any = object()


def _coerce(current: Any, value: str) -> Any:
    if isinstance(current, int) and not isinstance(current, bool):
        try:
            return int(value)
        except ValueError:
            try:
                number = float(value)
            except ValueError:
                return _UNCHANGED
            return int(number) if number.is_integer() else _UNCHANGED
    if isinstance(current, float):
        try:
            return float(value)
        except ValueError:
            return _UNCHANGED
    if isinstance(current, decimal.Decimal):
        try:
            return decimal.Decimal(value)
        except decimal.InvalidOperation:
            return _UNCHANGED
    return value
