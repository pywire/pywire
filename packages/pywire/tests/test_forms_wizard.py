"""Wizards: a model filled one sub-model step at a time, in every mode."""

import asyncio
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import pytest
from pydantic import BaseModel, EmailStr, Field, SecretStr, model_validator
from starlette.testclient import TestClient

from pywire.forms import Upload, Wizard, wizard
from pywire.forms.form import ACTION
from pywire.forms.wizard import STATE
from pywire.forms.wizard import _secret
from pywire.runtime.app import PyWire
from pywire.runtime.snapshot_codec import verify
from pywire.runtime.uploads import staging_for


class Account(BaseModel):
    email: EmailStr


class About(BaseModel):
    name: str = Field(min_length=2)
    avatar: Optional[Upload] = None


class Confirm(BaseModel):
    code: str
    password: Optional[SecretStr] = None


class Signup(BaseModel):
    account: Account
    about: About
    confirm: Confirm

    @model_validator(mode="after")
    def no_admins(self) -> "Signup":
        if self.account.email.startswith("admin@"):
            raise ValueError("Admins sign up elsewhere")
        return self


def post(w, data, handler=None, kind="submit"):
    asyncio.run(w._pw_submit(None, handler, {"type": kind, "formData": data}))


def hidden_state(w) -> str:
    html = w._pw_hidden_inputs()
    return re.search(r'value="([^"]+)"', html).group(1)


def test_wizard_needs_a_model_of_steps():
    class Flat(BaseModel):
        name: str

    with pytest.raises(TypeError, match="Flat.name is not"):
        wizard(Flat)


class Row(BaseModel):
    token: SecretStr


class Early(BaseModel):
    email: str
    password: SecretStr


class Rows(BaseModel):
    rows: list[Row] = []


class Done(BaseModel):
    ok: bool = True


@pytest.mark.parametrize(
    "steps,where",
    [
        ({"first": (Early, ...), "last": (Done, ...)}, "first.password"),
        ({"first": (Rows, ...), "last": (Done, ...)}, "first.rows.token"),
    ],
)
def test_secrets_must_be_on_the_last_step(steps, where):
    from pydantic import create_model

    model = create_model("Late", **steps)
    with pytest.raises(TypeError, match=rf"Late\.{where} is a secret"):
        wizard(model)
    # On the last step it is posted with the final submit, never carried.
    swapped = create_model("Ok", last=steps["last"], first=steps["first"])
    assert wizard(swapped).steps[-1].label == "First"


def test_steps_validate_one_at_a_time():
    w = wizard(Signup)
    assert isinstance(w, Wizard)
    assert (w.step, w.on_first_step, w.on_last_step) == ("account", True, False)
    assert [s.label for s in w.steps] == ["Account", "About", "Confirm"]

    post(w, {"account.email": "nope"})
    assert w.step == "account"
    assert w.errors == {"account.email": "Enter a valid email address"}

    post(w, {"account.email": "a@b.co"})
    assert w.step == "about"
    assert w.errors == {} and not w.submitted
    assert w.account.email.raw == "a@b.co"

    post(w, {"about.name": "A"})
    assert w.errors == {"about.name": "Use at least 2 characters"}
    post(w, {"about.name": "Al"})
    assert w.on_last_step


def test_back_keeps_what_was_typed():
    w = wizard(Signup)
    post(w, {"account.email": "a@b.co"})
    post(w, {"about.name": "Z", ACTION: "back"})
    assert w.step == "account" and w.errors == {}
    assert w.about.name.raw == "Z"
    post(w, {"account.email": "a@b.co"})
    assert w.step == "about" and w.about.name.raw == "Z"


def test_last_step_validates_everything_and_calls_the_handler():
    got = []
    w = wizard(Signup)
    post(w, {"account.email": "a@b.co"})
    post(w, {"about.name": "Al"})
    post(w, {"confirm.code": "123"}, handler=got.append)
    assert got[0].account.email == "a@b.co"
    assert got[0].about.name == "Al" and got[0].confirm.code == "123"


def test_whole_model_rules_run_on_the_last_step():
    got = []
    w = wizard(Signup)
    post(w, {"account.email": "admin@b.co"})
    post(w, {"about.name": "Al"})
    post(w, {"confirm.code": "123"}, handler=got.append)
    assert got == [] and w.on_last_step
    assert w.error == "Admins sign up elsewhere"


def test_live_validation_stays_on_the_current_step():
    w = wizard(Signup)
    post(w, {"account.email": "nope"}, kind="validate")
    # (the event's field is missing: nothing touched, nothing shown)
    assert w.errors == {}
    asyncio.run(
        w._pw_submit(
            None,
            None,
            {
                "type": "validate",
                "field": "account.email",
                "formData": {"account.email": "x"},
            },
        )
    )
    assert w.errors == {"account.email": "Enter a valid email address"}
    assert set(w._errors) == {"account.email"}


def test_state_travels_signed_for_no_js_posts():
    w = wizard(Signup)
    post(w, {"account.email": "a@b.co"})
    blob = hidden_state(w)

    # A fresh wizard (a no-JS POST renders a new page) picks up from the blob.
    fresh = wizard(Signup)
    post(fresh, {STATE: blob, "about.name": "Al"})
    assert fresh.step == "confirm"
    assert fresh.account.email.raw == "a@b.co"

    # An invalid last step re-renders; the password typed there isn't carried.
    post(fresh, {STATE: hidden_state(fresh), "confirm.password": "hunter2"})
    assert fresh.errors == {"confirm.code": "This field is required"}
    state = verify(hidden_state(fresh), secret=_secret(None))
    assert "confirm.password" not in state["raw"]

    got = []
    post(
        fresh,
        {STATE: hidden_state(fresh), "confirm.code": "1", "confirm.password": "pw"},
        handler=got.append,
    )
    assert got[0].account.email == "a@b.co"
    assert got[0].confirm.password.get_secret_value() == "pw"


def test_a_forged_state_is_ignored():
    w = wizard(Signup)
    post(w, {"account.email": "a@b.co"})
    blob = hidden_state(w)
    forged = blob[:-4] + ("AAAA" if not blob.endswith("AAAA") else "BBBB")
    fresh = wizard(Signup)
    post(fresh, {STATE: forged, "about.name": "Al"})
    assert fresh.step == "account"

    class Other(BaseModel):
        account: Account
        about: About

    other = wizard(Other)
    post(other, {STATE: blob})
    assert other.step == "account"


def test_files_travel_to_the_last_step():
    staging = staging_for(None)

    async def stage() -> Upload:
        async def body():
            yield b"img"

        upload_id = await staging.stage(
            body(), filename="a.png", content_type="image/png", limit=100
        )
        upload = await staging.get(upload_id)
        assert upload is not None
        return upload

    avatar = asyncio.run(stage())
    got = []
    w = wizard(Signup)
    post(w, {"account.email": "a@b.co"})
    post(w, {"about.name": "Al", "about.avatar": avatar})
    fresh = wizard(Signup)
    post(fresh, {STATE: hidden_state(w), "confirm.code": "1"}, handler=got.append)
    assert got[0].about.avatar.filename == "a.png"
    assert asyncio.run(got[0].about.avatar.read()) == b"img"


def test_snapshot_keeps_the_step():
    w = wizard(Signup)
    post(w, {"account.email": "a@b.co"})
    again = wizard(Signup)
    again.__pw_restore__(w.__pw_snapshot__())
    assert again.step == "about" and again.account.email.raw == "a@b.co"
    again.reset()
    assert again.step == "account" and again.account.email.raw == ""


PAGE = """---
from pydantic import BaseModel, Field
from pywire import wizard

class Account(BaseModel):
    email: str

class About(BaseModel):
    name: str = Field(min_length=2)

class Signup(BaseModel):
    account: Account
    about: About

signup = wizard(Signup)
done = wire("")

def create(data: Signup):
    done.value = f"{data.account.email}/{data.about.name}"
---
<form $bind={signup} @submit={create}>
  <input $if={signup.step == "account"} $bind={signup.account.email}>
  <input $if={signup.step == "about"} $bind={signup.about.name}>
  <p id="err">{signup.about.name.error or ""}</p>
  <button $if={not signup.on_first_step} {**signup.back_button}>Back</button>
  <button type="submit">{"Create" if signup.on_last_step else "Next"}</button>
</form>
<p id="done">{done}</p>
"""


@pytest.fixture(params=["interactive", "stateless"])
def client(request):
    root = Path(tempfile.mkdtemp())
    pages = root / "pages"
    pages.mkdir()
    (pages / "index.wire").write_text(PAGE)
    kwargs = {"stateless": True} if request.param == "stateless" else {}
    app = PyWire(pages_dir=str(pages), secret_key="wizard-secret", **kwargs)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    shutil.rmtree(root, ignore_errors=True)


def _hidden(html: str, name: str) -> str:
    return re.search(rf'name="{name}" value="([^"]+)"', html).group(1)


def test_a_wizard_works_without_javascript(client):
    html = client.get("/").text
    handler = _hidden(html, "__pywire_handler")
    assert 'name="account.email"' in html and ">Next</button>" in html

    r = client.post(
        "/",
        data={
            "__pywire_handler": handler,
            STATE: _hidden(html, STATE),
            "account.email": "a@b.co",
        },
    )
    assert r.status_code == 200
    assert 'name="about.name"' in r.text and 'name="account.email"' not in r.text

    r = client.post(
        "/",
        data={
            "__pywire_handler": handler,
            STATE: _hidden(r.text, STATE),
            "about.name": "A",
        },
    )
    assert r.status_code == 422
    assert "Use at least 2 characters" in r.text

    r = client.post(
        "/",
        data={
            "__pywire_handler": handler,
            STATE: _hidden(r.text, STATE),
            "about.name": "Al",
        },
    )
    assert r.status_code == 200
    assert ">a@b.co/Al</p>" in r.text
