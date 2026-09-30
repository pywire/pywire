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

import datetime as _dt
import decimal
import enum
import math
from typing import Any, Dict, List, Mapping, Optional, Set

from pywire.core.wire import WireBase, WireList, WireSet, _render_context
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
    if isinstance(value, enum.Enum):
        return _text(value.value)
    if isinstance(value, _dt.datetime):
        return value.isoformat(timespec="minutes")
    return str(value)


def _on(value: Any) -> bool:
    """Whether a boolean HTML attribute renders (``disabled={False}`` doesn't)."""
    return value is not None and value is not False


def _record(page: Any, handler: str, writable: bool, options: Any) -> None:
    """Remember what the element bound through ``handler`` accepts.

    A wire is written only through an element the page rendered editable,
    with a value among the ones it offered: the server never takes the
    client's word that a disabled box, a hidden ``$if`` or a missing option
    is editable.
    """
    if page is None or not handler:
        return
    state = page.__dict__.get("_pw_bind_state")
    if state is None:
        state = page.__dict__["_pw_bind_state"] = {}
    # The region rendering the element: when that region renders again,
    # the entry goes, and comes back only if the element is still there.
    context = _render_context.get()
    region = context[1] if context and context[0] is page else None
    # Components prefix handler names; the page dispatches the bare name.
    state[handler.rsplit(":", 1)[-1]] = {
        "writable": writable,
        "options": options,
        "region": region,
    }


def forget_region_binds(page: Any, region_id: Optional[str]) -> None:
    """Drop what elements rendered in ``region_id`` (and regions inside it)
    accept: the region is rendering again. ``None`` is a full render."""
    if region_id is None:
        page.__dict__["_pw_bind_state"] = {}
        page.__dict__["_pw_region_parent"] = {}
        return
    state = page.__dict__.get("_pw_bind_state")
    if not state:
        return
    parents: Dict[str, Optional[str]] = page.__dict__.get("_pw_region_parent") or {}

    def inside(region: Optional[str]) -> bool:
        seen: Set[str] = set()
        while region is not None and region not in seen:
            if region == region_id:
                return True
            seen.add(region)
            region = parents.get(region)
        return False

    for name in [n for n, entry in state.items() if inside(entry.get("region"))]:
        del state[name]


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
            '(e.g. term = wire("")) by its name, or a form field. A $for '
            "variable can't be bound to a wire: bind the wire by its own name."
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
    itype = str(out.get("type", "")).lower()
    writable = not (
        _on(out.get("disabled")) or _on(out.get("readonly")) or itype == "hidden"
    )
    options: Optional[Set[str]] = None
    if tag == "select":
        options = set()  # filled by option_attrs as the options render
    elif itype in ("checkbox", "radio") and not (
        isinstance(current, bool) and itype == "checkbox"
    ):
        options = {str(out["value"])}
    _record(page, handler, writable, options)
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


def bind_select(page: Any, site: str, obj: Any, handler: str = "") -> None:
    """Remember what a bound ``<select>`` holds, for its options."""
    selects: Optional[Dict[str, Any]] = getattr(page, "_pw_bound_selects", None)
    if selects is None:
        selects = page._pw_bound_selects = {}
    selects[site] = obj
    sites: Optional[Dict[str, str]] = page.__dict__.get("_pw_bind_sites")
    if sites is None:
        sites = page.__dict__["_pw_bind_sites"] = {}
    sites[site] = handler


def option_attrs(page: Any, site: str, attrs: Dict[str, Any]) -> Dict[str, Any]:
    """Mark a hand-written ``<option>`` selected when the binding holds it."""
    obj = (getattr(page, "_pw_bound_selects", None) or {}).get(site)
    if obj is None or "value" not in attrs:
        return attrs
    handler = (page.__dict__.get("_pw_bind_sites") or {}).get(site)
    entry = (page.__dict__.get("_pw_bind_state") or {}).get(handler or "")
    if (
        entry is not None
        and entry["options"] is not None
        and not _on(attrs.get("disabled"))
    ):
        entry["options"].add(str(attrs["value"]))
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


def apply_bind_event(
    target: Any, event: Mapping[str, Any], page: Any = None, handler: str = ""
) -> None:
    """Write what the user entered into a bound wire (generated handlers).

    The value is coerced to the type the wire holds. A number box that
    doesn't hold a number leaves the wire as it was, and so does a write
    through an element the page rendered disabled, read-only or not at all,
    or a value the element didn't offer.
    """
    if not _is_wire(target) or not isinstance(event, Mapping):
        return
    value = event.get("value")
    checked = event.get("checked")
    values = event.get("values")
    state = page.__dict__.get("_pw_bind_state") if page is not None else None
    if state is not None and handler:
        # (A page that never rendered here, like the HTTP fallback transport's,
        # has no state to check against.)
        entry = state.get(handler)
        if entry is None or not entry["writable"]:
            return
        options = entry["options"]
        if options is not None:
            if isinstance(values, list):
                values = [v for v in values if v in options]
            if isinstance(value, str) and value not in options:
                return
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
            number = float(value)
        except ValueError:
            return _UNCHANGED
        return number if math.isfinite(number) else _UNCHANGED
    if isinstance(current, decimal.Decimal):
        try:
            amount = decimal.Decimal(value)
        except decimal.InvalidOperation:
            return _UNCHANGED
        return amount if amount.is_finite() else _UNCHANGED
    if isinstance(current, enum.Enum):
        for member in type(current):
            if _text(member) == value:
                return member
        return _UNCHANGED
    if isinstance(current, (_dt.datetime, _dt.date, _dt.time)):
        try:
            return type(current).fromisoformat(value)
        except ValueError:
            return _UNCHANGED
    if current is None or isinstance(current, str):
        return value
    # A type the box can't hold (a list, a model): leave it.
    return _UNCHANGED
