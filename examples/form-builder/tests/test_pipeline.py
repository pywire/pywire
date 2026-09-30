"""The step machine, against fake OpenRouter and Jev."""

from __future__ import annotations

import anyio
import httpx
import pytest
from formbuilder import pipeline
from formbuilder.ai import OUT_OF_USAGE


def run_all(services, run):
    async def go():
        nonlocal run
        for _ in range(12):
            if not pipeline.running(run):
                return run
            run = await pipeline.advance(run, services)
        raise AssertionError("didn't finish")

    return anyio.run(go)


@pytest.fixture()
def services(fake_ai):
    import formbuilder

    return formbuilder.services()


def test_a_run_takes_one_model_call_per_step(services, fake_ai):
    run = run_all(services, pipeline.start("RSVP for a wedding"))
    assert not run["error"]
    steps = [(e["step"], e["engine"]) for e in run["log"]]
    assert steps == [
        ("check", "Jev"),
        ("draft", "OpenRouter"),
        ("decide", "Jev"),
        ("validate", "Code"),
        ("options", "OpenRouter"),  # the meal choice came without options
        ("validate", "Code"),
    ]
    assert [c["service"] for c in fake_ai.calls] == [
        "jev",
        "openrouter",
        "jev",
        "openrouter",
    ]
    fields = {f["name"]: f for f in run["spec"]["fields"]}
    assert fields["meal"]["options"] == ["Beef", "Fish", "Veg"]
    assert fields["notes"]["kind"] == "long_text"
    assert fields["notes"]["kind_confidence"] == 0.45
    assert fields["agree"]["required"] and not fields["notes"]["required"]


def test_the_writer_gets_a_strict_schema_and_jev_gets_typed_questions(
    services, fake_ai
):
    run_all(services, pipeline.start("RSVP for a wedding"))
    draft = fake_ai.calls[1]["body"]
    assert draft["model"] == "free/model:free"
    assert draft["response_format"]["json_schema"]["strict"] is True
    decide = fake_ai.calls[2]["body"]
    assert decide["model"] == "jev-latest"
    kind = decide["questions"]["kind.email"]
    assert kind["type"] == "choice" and set(kind["criteria"]) == set(
        pipeline.specs.KINDS
    )
    assert decide["questions"]["required.email"]["type"] == "noul"
    assert "email" in decide["state"]["fields"]


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ("sensitive", "passwords, payment details"),
        ("abusive", "won't build that one"),
        ("is_form", "doesn't read like a form"),
    ],
)
def test_the_check_step_stops_requests_we_wont_build(
    services, fake_ai, answer, message
):
    fake_ai.overrides[answer] = {
        "type": "noul",
        "noul": 0.1 if answer == "is_form" else 0.9,
    }
    run = run_all(services, pipeline.start("something"))
    assert message in run["error"]
    assert run["spec"] is None
    assert len(fake_ai.calls) == 1  # nothing was drafted


def test_sensitive_fields_from_the_writer_are_refused(services, fake_ai):
    fake_ai.overrides["form"] = {
        "title": "Login",
        "intro": "",
        "fields": [{"name": "pw", "label": "Password", "help": "", "options": []}],
    }
    run = run_all(services, pipeline.start("a sign-in form"))
    assert "passwords, payment details" in run["error"]


@pytest.mark.parametrize("status", [401, 402, 403, 429])
def test_usage_and_key_errors_say_the_author_is_out_of_usage(services, fake_ai, status):
    fake_ai.failure = httpx.Response(status, headers={"retry-after": "30"})
    run = run_all(services, pipeline.start("RSVP"))
    assert run["error"] == OUT_OF_USAGE
    assert run["log"][-1]["ok"] is False


def test_a_limited_model_falls_through_to_the_next(services, fake_ai):
    fake_ai.models["free/model:free"] = httpx.Response(429)
    run = run_all(services, pipeline.start("RSVP for a wedding"))
    assert not run["error"]
    tried = [c["body"]["model"] for c in fake_ai.calls if c["service"] == "openrouter"]
    assert tried[:2] == ["free/model:free", "paid/model"]


def test_a_reply_that_isnt_json_falls_through_to_the_next(services, fake_ai):
    fake_ai.models["free/model:free"] = "not json"
    run = run_all(services, pipeline.start("RSVP for a wedding"))
    assert not run["error"]
    assert run["spec"]["fields"]


def test_every_model_limited_says_the_author_is_out_of_usage(services, fake_ai):
    fake_ai.models["free/model:free"] = httpx.Response(429)
    fake_ai.models["paid/model"] = httpx.Response(402)
    run = run_all(services, pipeline.start("RSVP"))
    assert run["error"] == OUT_OF_USAGE


def test_a_refused_key_stops_without_trying_other_models(services, fake_ai):
    fake_ai.models["free/model:free"] = httpx.Response(401)
    run = run_all(services, pipeline.start("RSVP"))
    assert run["error"] == OUT_OF_USAGE
    assert "paid/model" not in [c["body"].get("model") for c in fake_ai.calls]


def test_other_upstream_errors_are_reported_plainly(services, fake_ai):
    fake_ai.failure = httpx.Response(500)
    run = run_all(services, pipeline.start("RSVP"))
    assert run["error"] == "TypeSafe returned an error (500)."


def test_refine_sends_the_current_form_and_the_change(services, fake_ai):
    first = run_all(services, pipeline.start("RSVP for a wedding"))
    fake_ai.calls.clear()
    run = run_all(
        services,
        pipeline.start(
            "RSVP for a wedding", instruction="drop the notes", base=first["spec"]
        ),
    )
    assert not run["error"]
    check, draft, decide = (c["body"] for c in fake_ai.calls[:3])
    assert check["state"]["change"] == "drop the notes"
    assert "drop the notes" in draft["messages"][1]["content"]
    assert decide["state"]["change"] == "drop the notes"
    assert decide["state"]["before"]["email"] == {"kind": "email", "required": True}


def test_sample_answers_are_checked_against_the_form(services):
    run = run_all(services, pipeline.start("RSVP for a wedding"))
    sample = anyio.run(pipeline.sample, run["spec"], services)
    assert sample["guests"] == 2
    assert sample["dietary"] == ["Vegan"]  # "Not an option" was dropped
    assert sample["agree"] is True
