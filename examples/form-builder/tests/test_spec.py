"""The spec rules: what a model's output can and can't turn into."""

from __future__ import annotations

import datetime

import pytest
from formbuilder import spec as specs
from pydantic import ValidationError


def field(name: str, kind: str, required: bool = True, options=()) -> dict:
    return {
        "name": name,
        "label": name.title(),
        "help": "",
        "options": list(options),
        "kind": kind,
        "required": required,
        "kind_confidence": 0.9,
        "required_score": 0.9,
    }


def test_names_are_slugged_deduped_and_kept_off_reserved_words():
    draft = specs.clean_draft(
        {
            "title": "T",
            "fields": [
                {"name": "Full Name!", "label": "Name"},
                {"name": "full name", "label": "Name again"},
                {"name": "class", "label": "Class"},
                {"name": "model_config", "label": "Config"},
                {"name": "2nd choice", "label": "Second"},
                {"name": "", "label": "Just a label"},
            ],
        }
    )
    names = [f["name"] for f in draft["fields"]]
    assert names == [
        "full_name",
        "full_name_2",
        "class_field",
        "model_config_field",
        "f_2nd_choice",
        "just_a_label",
    ]
    specs.build_model({**draft, "fields": draft["fields"]})


def test_everything_a_model_writes_is_capped():
    draft = specs.clean_draft(
        {
            "title": "x" * 500,
            "intro": "y" * 500,
            "fields": [
                {
                    "name": f"f{i}",
                    "label": "l" * 500,
                    "options": ["o"] * 3 + list("abcdefghijklmnop"),
                }
                for i in range(40)
            ],
        }
    )
    assert len(draft["title"]) == specs.MAX_TITLE
    assert len(draft["intro"]) == specs.MAX_INTRO
    assert len(draft["fields"]) == specs.MAX_FIELDS
    first = draft["fields"][0]
    assert len(first["label"]) == specs.MAX_LABEL
    assert len(first["options"]) == specs.MAX_OPTIONS
    assert first["options"][0] == "o"  # duplicates dropped


def test_junk_from_a_model_is_ignored():
    draft = specs.clean_draft(
        {"fields": [None, "text", {"label": 3, "options": "abc"}]}
    )
    assert draft["title"] == "Untitled form"
    assert [f["options"] for f in draft["fields"]] == [[]]


def test_refining_keeps_decisions_for_fields_that_keep_their_name():
    before = {"title": "T", "intro": "", "fields": [field("email", "email")]}
    draft = specs.clean_draft(
        {
            "fields": [
                {"name": "email", "label": "Email"},
                {"name": "age", "label": "Age"},
            ]
        },
        previous=before,
    )
    assert [(f["kind"], f["required"]) for f in draft["fields"]] == [
        ("email", True),
        ("text", False),
    ]


@pytest.mark.parametrize(
    "label",
    [
        "Password",
        "Card number",
        "Credit card",
        "CVV",
        "Social security number",
        "Bank account",
        "Passport number",
        "Seed phrase",
        "One-time code",
    ],
)
def test_sensitive_fields_are_refused_in_code(label):
    spec = {
        "title": "T",
        "intro": "",
        "fields": [{**field("x", "text"), "label": label}],
    }
    with pytest.raises(specs.SpecError, match="passwords, payment details"):
        specs.settle(spec)


def test_choice_without_options_becomes_text():
    spec = {
        "title": "T",
        "intro": "",
        "fields": [field("size", "choice", options=["M"])],
    }
    settled, notes = specs.settle(spec)
    assert settled["fields"][0]["kind"] == "text"
    assert notes == ["Size had no options, so it became short text"]


def test_unknown_kinds_become_text_and_empty_forms_are_refused():
    spec = {"title": "T", "intro": "", "fields": [field("a", "regex")]}
    assert specs.settle(spec)[0]["fields"][0]["kind"] == "text"
    with pytest.raises(specs.SpecError):
        specs.settle({"title": "T", "intro": "", "fields": []})


def test_the_model_enforces_each_kind():
    model = specs.build_model(
        {
            "title": "T",
            "intro": "",
            "fields": [
                field("email", "email"),
                field("site", "url", required=False),
                field("phone", "phone"),
                field("guests", "integer"),
                field("when", "date"),
                field("meal", "choice", options=["Fish", "Veg"]),
                field("extras", "multi_choice", options=["A", "B"]),
                field("agree", "checkbox"),
                field("news", "checkbox", required=False),
            ],
        }
    )
    ok = model.model_validate(
        {
            "email": "a@example.com",
            "phone": "+1 555 123 4567",
            "guests": "2",
            "when": "2026-10-01",
            "meal": "Fish",
            "extras": ["B"],
            "agree": True,
        }
    )
    assert ok.site is None and ok.news is False
    assert ok.when == datetime.date(2026, 10, 1)
    bad = {
        "email": "nope",
        "phone": "call me",
        "guests": "two",
        "when": "soon",
        "meal": "Beef",
        "extras": [],
        "agree": False,
    }
    with pytest.raises(ValidationError) as info:
        model.model_validate(bad)
    assert {e["loc"][0] for e in info.value.errors()} == set(bad)


def test_samples_that_dont_fit_are_dropped():
    spec = {
        "title": "T",
        "intro": "",
        "fields": [
            field("email", "email"),
            field("meal", "choice", options=["Fish", "Veg"]),
            field("extras", "multi_choice", options=["A", "B"]),
            field("guests", "integer"),
        ],
    }
    sample = specs.clean_sample(
        spec,
        {"email": ["nope"], "meal": ["Beef"], "extras": ["A", "Z"], "guests": ["3"]},
    )
    assert sample == {"extras": ["A"], "guests": 3}
