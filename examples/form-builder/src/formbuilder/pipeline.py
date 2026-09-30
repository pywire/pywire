"""Turn a sentence into a form, one model call per step.

A run is plain data kept in a wire. The page calls ``advance(run)`` once per
poll tick, and each call does at most one model request and returns the run
with that step done. So progress shows as it happens in both modes, and in
stateless mode no request runs longer than one model call: any server (or
Cloudflare isolate) can take the next step, because the run travels in the
signed snapshot.

The steps:

1. **check** (Jev): is this a form request, and is it one we won't build?
2. **draft** (OpenRouter): title, intro, and each field's name,
   label, help and options, as JSON matching a strict schema.
3. **decide** (Jev): for every field, which kind of answer it takes (a
   choice between the ``spec.KINDS``) and whether it's required. Each
   decision comes back with a probability.
4. **validate** (code): cap and clean everything, refuse sensitive fields.
   Choice fields without options get one **options** step
   (OpenRouter); any still without become short text.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from formbuilder import spec as specs
from formbuilder.ai import AIError, Jev, OpenRouter, noul

MAX_REQUEST = 400

WRITER = "OpenRouter"
DECIDER = "Jev"
CODE = "Code"

STEP_LABELS = {
    "check": "Check the request",
    "draft": "Write the fields",
    "decide": "Decide each field's type",
    "validate": "Validate the form",
    "options": "Write missing options",
}
STEP_ENGINES = {
    "check": DECIDER,
    "draft": WRITER,
    "decide": DECIDER,
    "validate": CODE,
    "options": WRITER,
}


@dataclass
class Services:
    writer: OpenRouter
    jev: Jev
    writer_models: Tuple[str, ...]


def start(request: str, *, instruction: str = "", base: Optional[dict] = None) -> dict:
    """A new run. With ``base`` and ``instruction`` it refines that spec."""
    return {
        "request": request.strip()[:MAX_REQUEST],
        "instruction": instruction.strip()[:MAX_REQUEST],
        "base": base,
        "todo": ["check", "draft", "decide", "validate"],
        "log": [],
        "spec": None,
        "error": "",
        "repaired": False,
    }


def running(run: Optional[dict]) -> bool:
    return bool(run and run["todo"] and not run["error"])


async def advance(run: dict, services: Services) -> dict:
    """Do the next step. Errors end the run with a message safe to show."""
    if not running(run):
        return run
    run = json.loads(json.dumps(run))  # never mutate the wire's value in place
    step = run["todo"].pop(0)
    began = time.perf_counter()
    entry: Dict[str, Any] = {
        "step": step,
        "label": STEP_LABELS[step],
        "engine": STEP_ENGINES[step],
        "ok": True,
        "note": "",
    }
    try:
        entry["note"] = await STEPS[step](run, services)
    except (AIError, specs.SpecError) as exc:
        entry["ok"] = False
        run["error"] = str(exc)
    entry["ms"] = round((time.perf_counter() - began) * 1000)
    run["log"].append(entry)
    if run["error"]:
        run["todo"] = []
    return run


# -- steps ---------------------------------------------------------------


async def _check(run: dict, services: Services) -> str:
    if run["base"]:
        state = {"form": _brief(run["base"]), "change": run["instruction"]}
        wants = "Is `change` asking to change the fields, wording or options of `form`?"
    else:
        state = {"request": run["request"]}
        wants = (
            "Is `request` asking for a form, survey, questionnaire, sign-up or "
            "order sheet that collects answers from people?"
        )
    answers = await services.jev.ask(
        state,
        {
            "is_form": {"type": "noul", "instructions": wants},
            "sensitive": {
                "type": "noul",
                "instructions": (
                    "Would the form described here ask people for passwords, payment "
                    "card or bank details, government ID numbers, or other secrets, "
                    "or is it meant to trick people into handing them over?"
                ),
            },
            "abusive": {
                "type": "noul",
                "instructions": "Is this hateful, sexual, or meant to harass or harm someone?",
            },
        },
    )
    is_form = noul(answers["is_form"])
    sensitive = noul(answers["sensitive"])
    abusive = noul(answers["abusive"])
    note = f"form request {is_form:.0%}, sensitive {sensitive:.0%}"
    if sensitive >= 0.5:
        raise specs.SpecError(
            "This demo doesn't build forms that ask for passwords, payment details "
            "or ID numbers."
        )
    if abusive >= 0.5:
        raise specs.SpecError("This demo won't build that one. Try another form.")
    if is_form < 0.5:
        raise specs.SpecError(
            "That doesn't read like a form. Try something like "
            "“RSVP for a wedding with a meal choice”."
            if not run["base"]
            else "That doesn't read like a change to this form. Try “make the phone "
            "number optional” or “add a field for dietary needs”."
        )
    return note


DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "intro": {"type": "string"},
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "label": {"type": "string"},
                    "help": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "label", "help", "options"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "intro", "fields"],
    "additionalProperties": False,
}

DRAFT_SYSTEM = f"""You design web forms. Reply with JSON only.

- title: a short title for the form.
- intro: one plain sentence telling people what the form is for, or "".
- fields: at most {specs.MAX_FIELDS}, in the order people should fill them in.
  - name: snake_case, unique.
  - label: what the person sees, in the language of the request.
  - help: a short hint, or "" when the label says enough.
  - options: the answers to pick from when the answer comes from a fixed
    list (a meal, a size, a rating); [] for everything else.
- Never add fields for passwords, payment card or bank details, or ID numbers.
- Don't add a submit button or anything that isn't a question."""


async def _draft(run: dict, services: Services) -> str:
    if run["base"]:
        user = (
            "Here is a form as JSON:\n"
            + json.dumps(_brief(run["base"]))
            + "\n\nApply this change and return the whole updated form: "
            + run["instruction"]
        )
    else:
        user = "Design a form for: " + run["request"]
    raw = await services.writer.json(
        services.writer_models, DRAFT_SYSTEM, user, "form", DRAFT_SCHEMA
    )
    spec = specs.clean_draft(raw, previous=run["base"])
    run["spec"] = spec
    return f"{len(spec['fields'])} fields"


async def _decide(run: dict, services: Services) -> str:
    spec = run["spec"]
    if not spec["fields"]:
        raise specs.SpecError("The form came back with no fields. Try again.")
    state: Dict[str, Any] = {
        "request": run["request"],
        "fields": {
            f["name"]: {"label": f["label"], "help": f["help"], "options": f["options"]}
            for f in spec["fields"]
        },
    }
    if run["base"]:
        state["change"] = run["instruction"]
        state["before"] = {f["name"]: _decision(f) for f in run["base"]["fields"]}
    questions: Dict[str, Any] = {}
    for f in spec["fields"]:
        ref = f"`fields.{f['name']}`"
        questions[f"kind.{f['name']}"] = {
            "type": "choice",
            "instructions": f"What kind of answer does the form field {ref} ask for?",
            "criteria": specs.KINDS,
        }
        questions[f"required.{f['name']}"] = {
            "type": "noul",
            "instructions": (
                f"Should people have to answer {ref} before they can send the form?"
                + (" Follow `change` where it says." if run["base"] else "")
            ),
        }
    answers = await services.jev.ask(state, questions)
    unsure = 0
    for f in spec["fields"]:
        kind = answers[f"kind.{f['name']}"]
        choice = kind.get("choice") if isinstance(kind, dict) else None
        f["kind"] = choice if choice in specs.KINDS else "text"
        confidence = kind.get("confidence") if isinstance(kind, dict) else None
        f["kind_confidence"] = (
            float(confidence) if isinstance(confidence, (int, float)) else None
        )
        f["required_score"] = noul(answers[f"required.{f['name']}"])
        f["required"] = f["required_score"] >= 0.5
        if (f["kind_confidence"] or 0) < 0.6:
            unsure += 1
    note = f"{len(questions)} decisions"
    return note + (f", {unsure} unsure" if unsure else "")


async def _validate(run: dict, services: Services) -> str:
    spec = run["spec"]
    missing = specs.missing_options(spec)
    if missing and not run["repaired"]:
        run["repaired"] = True
        run["todo"][:0] = ["options", "validate"]
        return (
            f"{len(missing)} choice field{'s' if len(missing) > 1 else ''} need options"
        )
    spec, notes = specs.settle(spec)
    specs.build_model(spec)  # proves pydantic accepts it
    run["spec"] = spec
    return "; ".join(notes) or "ready"


OPTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "options"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["fields"],
    "additionalProperties": False,
}


async def _options(run: dict, services: Services) -> str:
    spec = run["spec"]
    missing = set(specs.missing_options(spec))
    wanted = [
        {"name": f["name"], "label": f["label"], "help": f["help"]}
        for f in spec["fields"]
        if f["name"] in missing
    ]
    raw = await services.writer.json(
        services.writer_models,
        "You write answer options for form fields. Reply with JSON only. Give "
        "each field 2 to 8 short options, in the language of its label.",
        f"Form: {spec['title']}\nFields: {json.dumps(wanted)}",
        "options",
        OPTIONS_SCHEMA,
        max_tokens=800,
    )
    by_name = {
        item.get("name"): item.get("options")
        for item in (raw.get("fields") or [])
        if isinstance(item, dict)
    }
    filled = 0
    for f in spec["fields"]:
        if f["name"] in missing:
            f["options"] = specs.clean_options(by_name.get(f["name"]))
            filled += len(f["options"]) >= 2
    return f"{filled} of {len(missing)} filled"


STEPS: Dict[str, Callable[[dict, Services], Awaitable[str]]] = {
    "check": _check,
    "draft": _draft,
    "decide": _decide,
    "validate": _validate,
    "options": _options,
}


# -- sample answers --------------------------------------------------------

SAMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "values": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "values"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["answers"],
    "additionalProperties": False,
}


async def sample(spec: dict, services: Services) -> dict:
    """Believable answers for the form, checked against its model."""
    fields = [
        {
            "name": f["name"],
            "label": f["label"],
            "kind": f["kind"],
            "options": f["options"],
        }
        for f in spec["fields"]
    ]
    raw = await services.writer.json(
        services.writer_models,
        "You fill in forms with realistic example answers. Reply with JSON only. "
        "One entry per field. values holds one answer, or several for "
        "multi_choice. Use only the given options for choice fields, ISO dates "
        "(YYYY-MM-DD), and example.com addresses for emails.",
        f"Form: {spec['title']}\nFields: {json.dumps(fields)}",
        "answers",
        SAMPLE_SCHEMA,
        max_tokens=1200,
    )
    values: Dict[str, List[str]] = {}
    for item in raw.get("answers") or []:
        if isinstance(item, dict) and isinstance(item.get("values"), list):
            values[str(item.get("name"))] = [
                str(v)[:500] for v in item["values"] if isinstance(v, (str, int, float))
            ]
    return specs.clean_sample(spec, values)


# -- helpers -----------------------------------------------------------------


def _decision(field: dict) -> dict:
    return {"kind": field["kind"], "required": field["required"]}


def _brief(spec: dict) -> dict:
    """The spec as the models see it: no confidence numbers."""
    return {
        "title": spec["title"],
        "intro": spec["intro"],
        "fields": [
            {
                "name": f["name"],
                "label": f["label"],
                "help": f["help"],
                "options": f["options"],
                **_decision(f),
            }
            for f in spec["fields"]
        ],
    }
