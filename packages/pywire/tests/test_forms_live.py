"""Live validation: a bound form checks fields as the user leaves them."""

import asyncio
import re

import pytest
from starlette.requests import Request

from pywire.runtime.loader import PageLoader

_SCOPE = {
    "type": "http",
    "http_version": "1.1",
    "method": "GET",
    "path": "/",
    "raw_path": b"/",
    "root_path": "",
    "query_string": b"",
    "headers": [(b"host", b"localhost")],
    "scheme": "http",
    "server": ("localhost", 80),
    "client": ("127.0.0.1", 1),
}

PAGE = """---
from pydantic import BaseModel, EmailStr, Field, model_validator
from pywire import form

class Signup(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2)
    city: str = ""

    @model_validator(mode="after")
    def not_admin(self):
        if self.name == "admin":
            raise ValueError("Pick another name")
        return self

signup = form(Signup{extra})
saved = wire("")

def create(data: Signup):
    saved.value = data.email
---
<form $bind={{signup}} @submit={{create}}>
  <input $bind={{signup.email}}>
  <p id="email-error">{{signup.email.error}}</p>
  <input $bind={{signup.name}}>
  <p id="name-error">{{signup.name.error}}</p>
  <p id="form-error">{{signup.error}}</p>
</form>
"""


def _page(tmp_path, extra=""):
    f = tmp_path / "page.wire"
    f.write_text(PAGE.format(extra=extra))
    cls = PageLoader().load(f, use_cache=False)
    page = cls(request=Request(_SCOPE), params={}, query={}, path={"main": True})
    asyncio.run(page.render())
    return page


def _html(page) -> str:
    return asyncio.run(page.render()).body.decode()


def _send(page, kind, data, field=None):
    event = {"type": kind, "formData": data}
    if field is not None:
        event["field"] = field
    asyncio.run(page.handle_event("_handler_0", event))


def test_only_left_fields_show_errors(tmp_path):
    page = _page(tmp_path)
    _send(page, "validate", {"email": "nope", "name": "A"}, field="email")
    assert page.signup.email.error == "Enter a valid email address"
    assert page.signup.name.error is None  # not reached yet
    assert page.signup.errors == {"email": "Enter a valid email address"}
    assert page.signup.valid is False
    assert page.saved.value == ""  # validation never calls the handler


def test_submit_shows_every_error(tmp_path):
    page = _page(tmp_path)
    _send(page, "validate", {"email": "nope", "name": "A"}, field="email")
    _send(page, "submit", {"email": "nope", "name": "A"})
    assert page.signup.name.error == "Use at least 2 characters"


def test_form_level_errors_wait_for_submit(tmp_path):
    page = _page(tmp_path)
    data = {"email": "a@b.co", "name": "admin"}
    _send(page, "validate", data, field="name")
    assert page.signup.error is None
    _send(page, "submit", data)
    assert page.signup.error == "Pick another name"


def test_fixing_a_field_clears_its_error(tmp_path):
    page = _page(tmp_path)
    _send(page, "validate", {"email": "nope", "name": "Al"}, field="email")
    _send(page, "validate", {"email": "a@b.co", "name": "Al"}, field="email")
    assert page.signup.email.error is None
    assert page.signup.valid is True
    assert page.signup.value is None  # .value comes from a submit


def test_rendered_state(tmp_path):
    page = _page(tmp_path)
    html = _html(page)
    assert 'data-pw-validate="blur"' in re.search(r"<form[^>]*>", html).group(0)
    _send(page, "validate", {"email": "nope", "name": "A"}, field="email")
    html = _html(page)
    email = re.search(r'<input[^>]*name="email"[^>]*>', html).group(0)
    assert 'aria-invalid="true"' in email and "autofocus" not in email
    assert '<p id="email-error">Enter a valid email address</p>' in html


def test_first_invalid_field_autofocuses_after_submit(tmp_path):
    page = _page(tmp_path)
    _send(page, "submit", {"email": "nope", "name": "A"})
    html = _html(page)
    email = re.search(r'<input[^>]*name="email"[^>]*>', html).group(0)
    name = re.search(r'<input[^>]*name="name"[^>]*>', html).group(0)
    assert "autofocus" in email and "autofocus" not in name


def test_submit_only_forms_ignore_live_checks(tmp_path):
    page = _page(tmp_path, extra=', validate="submit"')
    assert "data-pw-validate" not in _html(page)
    _send(page, "validate", {"email": "nope"}, field="email")
    assert page.signup.email.error is None
    assert page.signup.valid is True


def test_an_error_set_in_code_shows_at_once(tmp_path):
    page = _page(tmp_path)
    page.signup.email.error = "That email is taken"
    assert page.signup.email.error == "That email is taken"


def test_touched_fields_survive_a_snapshot(tmp_path):
    page = _page(tmp_path)
    _send(page, "validate", {"email": "nope", "name": "A"}, field="email")
    state = page.signup.__pw_snapshot__()
    assert state["touched"] == ["email"]
    other = _page(tmp_path)
    other.signup.__pw_restore__(state)
    assert other.signup.email.error == "Enter a valid email address"
    assert other.signup.name.error is None


def test_bad_validate_mode():
    from pydantic import BaseModel

    from pywire import form

    class M(BaseModel):
        x: str

    with pytest.raises(ValueError, match="validate="):
        form(M, validate="keystroke")  # type: ignore[arg-type]
