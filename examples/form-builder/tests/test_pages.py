"""The page end to end, in stateless mode and over the WebSocket.

``tab`` runs every test twice: once as one POST per event with the state in
a signed snapshot, once as a live WebSocket session.
"""

from __future__ import annotations

import re

import httpx
from formbuilder.ai import OUT_OF_USAGE


def text_of(html: str, element_id: str) -> str:
    found = re.findall(rf'id="{element_id}"[^>]*>(.*?)</', html, re.S)
    return found[-1] if found else ""


def test_the_page_renders_and_gives_a_visitor_cookie(apps):
    client = apps["stateless"]
    client.cookies.clear()
    response = client.get("/")
    assert response.status_code == 200
    assert "Build the form" in response.text
    assert "fb_visitor=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]


def test_build_shows_each_step_then_a_working_form(tab):
    html = tab.build("RSVP for a wedding")
    labels = re.findall(r'<span class="what">([^<]*)</span>', html)
    assert "Check the request" in labels and "Write missing options" in labels
    assert 'id="preview"' in html
    assert '<select name="meal"' in html
    assert 'type="email"' in html
    assert '<textarea rows="3" name="notes"' in html
    assert 'value="Vegan" name="dietary"' in html
    # The unsure decision is marked.
    assert re.search(
        r'class="decision unsure"><span class="what">Anything else\?', html
    )


def test_the_generated_form_validates_on_the_server(tab):
    tab.build("RSVP for a wedding")
    html = tab.submit("preview", full_name="", email="nope", guests="two", meal="Soup")
    assert "This field is required" in html
    assert 'aria-invalid="true"' in html
    assert 'id="accepted"' not in html

    html = tab.submit(
        "preview",
        full_name="Ada",
        email="ada@example.com",
        guests="2",
        meal="Fish",
        dietary=["Vegan"],
        agree="true",
    )
    accepted = re.sub(r">\s+<", "><", html[html.find('id="accepted"') :])
    assert "<dt>Guests</dt><dd>2</dd>" in accepted
    assert "<dt>Dietary needs</dt><dd>Vegan</dd>" in accepted
    assert "<dt>Anything else?</dt><dd>(empty)</dd>" in accepted


def test_sample_answers_fill_the_form(tab):
    tab.build("RSVP for a wedding")
    handler, _ = tab.handler("click", "Fill with sample answers")
    html = tab.fire(handler)
    assert 'value="ada@example.com"' in html
    assert re.search(r'value="Fish"[^>]*selected|selected[^>]*value="Fish"', html)


def test_refine_rebuilds_from_the_current_form(tab, fake_ai):
    tab.build("RSVP for a wedding")
    fake_ai.calls.clear()
    handler = re.findall(
        r'<form data-on-submit="(\w+)"[^>]*>\s*<label for="instruction"', tab.page
    )[-1]
    html = tab.build("", handler=handler, instruction="make guests optional")
    assert fake_ai.calls[0]["body"]["state"]["change"] == "make guests optional"
    assert 'id="preview"' in html


def test_out_of_usage_shows_the_authors_message(tab, fake_ai):
    fake_ai.failure = httpx.Response(429)
    html = tab.build("RSVP for a wedding")
    assert OUT_OF_USAGE.replace("'", "&#x27;") in html or OUT_OF_USAGE in html
    assert 'id="preview"' not in html


def test_a_request_that_isnt_a_form_is_turned_away(tab, fake_ai):
    fake_ai.overrides["is_form"] = {"type": "noul", "noul": 0.05}
    html = tab.build("what's the weather tomorrow")
    assert "doesn&#x27;t read like a form" in html or "doesn't read like a form" in html
    assert [c["service"] for c in fake_ai.calls] == ["jev"]


def test_each_visitor_is_rate_limited(tab, fake_ai, monkeypatch):
    import formbuilder
    from formbuilder.limits import MemoryLimiter

    class OnePerVisitor(MemoryLimiter):
        def take(self, key, limit, window):
            return super().take(key, 1, window)

    monkeypatch.setattr(formbuilder, "limiter", OnePerVisitor())
    tab.build("RSVP for a wedding")
    calls = len(fake_ai.calls)
    html = tab.fire("build", formData={"request": "another one"})
    assert "used this demo a lot" in text_of(html, "notice")
    assert len(fake_ai.calls) == calls


def test_empty_request_asks_for_one(tab, fake_ai):
    html = tab.fire("build", formData={"request": "   "})
    assert text_of(html, "notice") == "Describe the form you want first."
    assert fake_ai.calls == []


def test_a_field_is_checked_when_the_visitor_leaves_it(tab):
    tab.build("RSVP for a wedding")
    handler, hidden = tab.form("preview")
    html = tab.fire(
        handler,
        type="validate",
        field="email",
        formData={**hidden, "email": "nope"},
    )
    assert re.search(r'id="preview-email-error"[^>]*>[^<]+', html)
