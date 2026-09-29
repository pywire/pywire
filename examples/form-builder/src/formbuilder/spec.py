"""The form spec: what the models produce, what code checks, what pywire renders.

A spec is plain JSON-friendly data so it can live in a wire (and so in the
signed snapshot in stateless mode)::

    {"title": "...", "intro": "...", "fields": [
        {"name": "email", "label": "Email", "help": "", "options": [],
         "kind": "email", "required": True,
         "kind_confidence": 0.93, "required_score": 0.88},
    ]}

Nothing a model writes is ever executed. Field names are slugged, every
string is capped, and the only types a field can have are the ones in
``KINDS``, each mapped to a fixed Pydantic type below. There is no free-form
regex or code path: the model picks from a menu.
"""

from __future__ import annotations

import datetime
import keyword
import re
from typing import Any, List, Literal, Optional, Tuple

from pydantic import BaseModel, EmailStr, Field, HttpUrl, TypeAdapter, create_model

MAX_FIELDS = 12
MAX_OPTIONS = 12
MAX_TITLE = 80
MAX_INTRO = 240
MAX_LABEL = 80
MAX_HELP = 160
MAX_OPTION = 60
MAX_NAME = 40

# What a field can be. The descriptions are the criteria Jev chooses by, so
# they describe the answer a person gives, not the widget.
KINDS: dict[str, str] = {
    "text": "A short free-text answer: a name, a title, a city, a few words.",
    "long_text": "A longer free-text answer of a sentence or more: a description, comments, a message.",
    "email": "An email address.",
    "url": "A web address or link.",
    "phone": "A phone number.",
    "number": "A number that can have decimals: an amount of money, a weight, a distance.",
    "integer": "A whole number: a count, a quantity, an age, a number of people.",
    "date": "A calendar date.",
    "choice": "Exactly one answer picked from a fixed list of options.",
    "multi_choice": "Any number of answers picked from a fixed list of options.",
    "checkbox": "A single yes or no: agreeing to something, opting in, a toggle.",
}
CHOICE_KINDS = frozenset({"choice", "multi_choice"})

KIND_LABELS: dict[str, str] = {
    "text": "Short text",
    "long_text": "Long text",
    "email": "Email",
    "url": "Link",
    "phone": "Phone",
    "number": "Number",
    "integer": "Whole number",
    "date": "Date",
    "choice": "Pick one",
    "multi_choice": "Pick any",
    "checkbox": "Yes or no",
}

PHONE_PATTERN = r"^\+?[0-9][0-9 ()\-.]{5,22}$"

# Names a generated field can't take: Python keywords, BaseModel attributes,
# and the members of pywire's Form and BoundField.
_RESERVED = (
    set(keyword.kwlist)
    | {name for name in dir(BaseModel)}
    | {
        "value", "valid", "error", "errors", "dirty", "submitted", "fields",
        "model", "load", "reset", "label", "help", "required", "options", "raw",
        "attrs", "html_name", "html_id", "error_id", "add_button", "remove_button",
    }
)  # fmt: skip

# Things this demo refuses to ask for, whatever the models say. A public
# page that builds forms on request is a phishing kit if it will ask for
# these, so the check is in code as well as in Jev's guard question.
_SENSITIVE = re.compile(
    r"pass(word|code|phrase)|\bpin\b|\bcvc\b|\bcvv\b|card.?(number|no\b)|credit.?card"
    r"|debit.?card|\bssn\b|social.?security|bank.?account|routing|\biban\b|sort.?code"
    r"|passport|driv\w*.?licen[cs]e|seed.?phrase|recovery.?phrase|private.?key"
    r"|security.?(question|answer)|one.?time.?code|\b2fa\b|\botp\b",
    re.IGNORECASE,
)


class SpecError(ValueError):
    """The spec can't be used; the message is safe to show."""


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def slug(value: Any) -> str:
    """A snake_case field name, safe as a Python identifier and model field."""
    name = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")[:MAX_NAME]
    name = name.strip("_") or "field"
    if name[0].isdigit():
        name = "f_" + name
    if name in _RESERVED or name.startswith("model_"):
        name += "_field"
    return name


def clean_options(values: Any) -> List[str]:
    seen: dict[str, str] = {}
    for value in values if isinstance(values, list) else []:
        text = _text(value, MAX_OPTION)
        if text and text.lower() not in seen:
            seen[text.lower()] = text
    return list(seen.values())[:MAX_OPTIONS]


def clean_draft(raw: Any, previous: Optional[dict] = None) -> dict:
    """Keep what's usable from a drafted form and cap everything.

    ``previous`` is the spec being refined: fields that keep their name keep
    their earlier decisions until Jev decides again.
    """
    raw = raw if isinstance(raw, dict) else {}
    before = {f["name"]: f for f in (previous or {}).get("fields", [])}
    fields: List[dict] = []
    names: set[str] = set()
    for item in raw.get("fields") or []:
        if not isinstance(item, dict) or len(fields) >= MAX_FIELDS:
            continue
        label = _text(item.get("label"), MAX_LABEL)
        name = slug(item.get("name") or label)
        base, n = name, 2
        while name in names:
            name, n = f"{base}_{n}", n + 1
        names.add(name)
        old = before.get(name, {})
        fields.append(
            {
                "name": name,
                "label": label or name.replace("_", " ").capitalize(),
                "help": _text(item.get("help"), MAX_HELP),
                "options": clean_options(item.get("options")),
                "kind": old.get("kind", "text"),
                "required": old.get("required", False),
                "kind_confidence": None,
                "required_score": None,
            }
        )
    return {
        "title": _text(raw.get("title"), MAX_TITLE) or "Untitled form",
        "intro": _text(raw.get("intro"), MAX_INTRO),
        "fields": fields,
    }


def sensitive_fields(spec: dict) -> List[str]:
    """Labels of fields that ask for secrets or payment and ID details."""
    return [
        f["label"]
        for f in spec["fields"]
        if _SENSITIVE.search(f"{f['name']} {f['label']} {f['help']}")
    ]


def missing_options(spec: dict) -> List[str]:
    """Names of choice fields without at least two options."""
    return [
        f["name"]
        for f in spec["fields"]
        if f["kind"] in CHOICE_KINDS and len(f["options"]) < 2
    ]


def settle(spec: dict) -> Tuple[dict, List[str]]:
    """Make the spec buildable; returns it and a note per change made."""
    notes = []
    for f in spec["fields"]:
        if f["kind"] not in KINDS:
            f["kind"] = "text"
        if f["kind"] in CHOICE_KINDS and len(f["options"]) < 2:
            notes.append(f"{f['label']} had no options, so it became short text")
            f["kind"] = "text"
        if f["kind"] not in CHOICE_KINDS:
            f["options"] = []
    if not spec["fields"]:
        raise SpecError("The form came back with no fields. Try describing it again.")
    labels = sensitive_fields(spec)
    if labels:
        raise SpecError(
            "This demo doesn't build forms that ask for passwords, payment details "
            f"or ID numbers ({', '.join(labels)})."
        )
    return spec, notes


def annotation(field: dict) -> Any:
    """The Pydantic type for one field."""
    kind = field["kind"]
    if kind == "long_text":
        return str, {"max_length": 2000}
    if kind == "email":
        return EmailStr, {}
    if kind == "url":
        return HttpUrl, {}
    if kind == "phone":
        return str, {"pattern": PHONE_PATTERN}
    if kind == "number":
        return float, {}
    if kind == "integer":
        return int, {}
    if kind == "date":
        return datetime.date, {}
    if kind == "choice":
        return Literal[tuple(field["options"])], {}
    if kind == "multi_choice":
        return List[Literal[tuple(field["options"])]], {}
    if kind == "checkbox":
        return bool, {}
    return str, {"max_length": 200}


def build_model(spec: dict) -> type[BaseModel]:
    """A Pydantic model for the spec. The name is fixed: pywire signs a
    form's posted state with the model's name."""
    definitions: dict[str, Any] = {}
    for f in spec["fields"]:
        tp, rules = annotation(f)
        info = {"title": f["label"], "description": f["help"] or None, **rules}
        kind, required = f["kind"], f["required"]
        if kind == "checkbox":
            # A required checkbox is one that must be ticked ("I agree").
            tp = Literal[True] if required else bool
            definitions[f["name"]] = (tp, Field(... if required else False, **info))
        elif kind == "multi_choice":
            if required:
                info["min_length"] = 1
            definitions[f["name"]] = (tp, Field(... if required else [], **info))
        elif required:
            definitions[f["name"]] = (tp, Field(..., **info))
        else:
            definitions[f["name"]] = (Optional[tp], Field(None, **info))
    return create_model("GeneratedForm", **definitions)


def clean_sample(spec: dict, values: dict[str, List[str]]) -> dict[str, Any]:
    """Sample answers that fit the spec; anything that doesn't is dropped."""
    model = build_model(spec)
    sample: dict[str, Any] = {}
    for f in spec["fields"]:
        given = values.get(f["name"]) or []
        if f["kind"] == "multi_choice":
            candidate: Any = [v for v in given if v in f["options"]]
        elif f["kind"] == "checkbox":
            candidate = bool(given) and given[0].strip().lower() in {"true", "yes", "1"}
            if f["required"]:
                candidate = True
        elif given:
            candidate = given[0]
        else:
            continue
        adapter = TypeAdapter(model.model_fields[f["name"]].annotation)
        try:
            # JSON-friendly, so the sample can live in a wire.
            sample[f["name"]] = adapter.dump_python(
                adapter.validate_python(candidate), mode="json"
            )
        except ValueError:
            continue
    return sample


def jsonable(values: dict[str, Any]) -> List[Tuple[str, str]]:
    """Validated values as (label, text) rows for display."""
    rows = []
    for key, value in values.items():
        if isinstance(value, list):
            text = ", ".join(str(v) for v in value) or "(none)"
        elif value is None:
            text = "(empty)"
        elif isinstance(value, bool):
            text = "Yes" if value else "No"
        else:
            text = str(value)
        rows.append((key, text))
    return rows
