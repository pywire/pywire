"""``$bind`` codegen: the model writes the HTML, and the submit wrapper is
the only way a client reaches the handler."""

import asyncio
import re
import sys

import pytest
from starlette.requests import Request

from pywire.compiler.exceptions import PyWireSyntaxError
from pywire.forms.render import BindError
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

MODEL = """
from typing import Literal, Optional
from pydantic import BaseModel, EmailStr, Field
from pywire import form

class Signup(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2, max_length=50)
    age: int = Field(ge=13)
    plan: Literal["free", "pro"] = "free"
    country: str = "se"
    colors: list[Literal["red", "blue"]] = []
    bio: str = ""
    terms: Literal[True]
    note: Optional[str] = None
"""

PAGE = (
    "---"
    + MODEL
    + """
signup = form(Signup)
done = wire("")

async def create(data: Signup):
    done.value = data.email
---
<form $bind={signup} @submit={create} class="f">
  <label for={signup.email.html_id}>{signup.email.label}</label>
  <input $bind={signup.email} placeholder="you@example.com">
  <p id={signup.email.error_id} $if={signup.email.error}>{signup.email.error}</p>
  <input $bind={signup.name}>
  <input $bind={signup.age}>
  <select $bind={signup.plan}></select>
  <select $bind={signup.country}>
    <option value="se">Sweden</option>
    <option value="no">Norway</option>
  </select>
  <label><input type="radio" value="free" $bind={signup.plan}> Free</label>
  <label><input type="radio" value="pro" $bind={signup.plan}> Pro</label>
  <input type="checkbox" value="red" $bind={signup.colors}>
  <input type="checkbox" value="blue" $bind={signup.colors}>
  <textarea $bind={signup.bio}></textarea>
  <input $bind={signup.terms}>
  <input $bind={signup.note} disabled>
</form>
<p id="done">{done}</p>
"""
)


def _load(tmp_path, source, name="page"):
    f = tmp_path / f"{name}.wire"
    f.write_text(source)
    return PageLoader().load(f, use_cache=False)


def _page(cls):
    return cls(request=Request(_SCOPE), params={}, query={}, path={"main": True})


def _render(page) -> str:
    return asyncio.run(page.render()).body.decode()


def _tag(html: str, pattern: str) -> str:
    match = re.search(pattern, html)
    assert match is not None, f"{pattern!r} not in {html}"
    return match.group(0)


@pytest.fixture()
def page(tmp_path):
    return _page(_load(tmp_path, PAGE))


def test_only_the_wrapper_is_dispatchable(page):
    assert type(page).__event_handlers__ == frozenset({"_handler_0"})
    with pytest.raises(ValueError, match="not a registered event handler"):
        asyncio.run(page._dispatch_handler("create", {"formData": VALID}))


def test_form_element(page):
    html = _render(page)
    form = _tag(html, r"<form[^>]*>")
    assert 'method="post"' in form and 'data-on-submit="_handler_0"' in form
    assert 'id="signup"' in form and 'class="f"' in form
    assert '<input type="hidden" name="__pywire_handler" value="_handler_0">' in html


def test_field_attributes_come_from_the_model(page):
    html = _render(page)
    email = _tag(html, r'<input[^>]*name="email"[^>]*>')
    assert 'type="email"' in email and " required" in email
    assert 'placeholder="you@example.com"' in email and 'id="signup-email"' in email
    name = _tag(html, r'<input[^>]*name="name"[^>]*>')
    assert 'minlength="2"' in name and 'maxlength="50"' in name
    age = _tag(html, r'<input[^>]*name="age"[^>]*>')
    assert 'type="number"' in age and 'min="13"' in age
    assert '<label for="signup-email">Email</label>' in html


def test_select_options_and_choices(page):
    html = _render(page)
    assert (
        '<select name="plan" id="signup-plan"><option value="free" selected>Free'
        '</option><option value="pro">Pro</option></select>'
    ) in html
    assert re.search(r'<option value="se" selected>Sweden', html)
    assert re.search(r'type="radio"[^>]*value="free"[^>]*checked', html)
    assert not re.search(r'type="radio"[^>]*value="pro"[^>]*checked', html)
    terms = _tag(html, r'<input[^>]*name="terms"[^>]*>')
    assert (
        'type="checkbox"' in terms and 'value="true"' in terms and " required" in terms
    )
    assert 'id="signup-terms"' in terms
    # Each radio and checkbox of a group gets its own id
    assert 'id="signup-plan-free"' in html and 'id="signup-plan-pro"' in html
    assert 'id="signup-colors-red"' in html and 'id="signup-colors-blue"' in html


VALID = {"email": "a@b.co", "name": "Al", "age": "20", "terms": "true"}


def _submit(page, data):
    return asyncio.run(page.handle_event("_handler_0", {"formData": data}))


def test_invalid_submit_rerenders_values_and_errors(page):
    _render(page)
    update = _submit(
        page,
        {
            "email": "bad",
            "name": "A",
            "age": "9",
            "country": "no",
            "plan": "pro",
            "colors": ["blue"],
            "bio": "hi <b>",
        },
    )
    html = "".join(r.get("html", "") for r in update["regions"])
    email = _tag(html, r'<input[^>]*name="email"[^>]*>')
    assert 'value="bad"' in email and 'aria-invalid="true"' in email
    assert 'aria-describedby="signup-email-error"' in email
    assert '<p id="signup-email-error">Enter a valid email address</p>' in html
    assert re.search(r'<option value="no" selected>Norway', html)
    assert not re.search(r'<option value="se" selected>', html)
    assert re.search(r'type="radio"[^>]*value="pro"[^>]*checked', html)
    assert re.search(r'value="blue"[^>]*checked', html)
    assert not re.search(r'value="red"[^>]*checked', html)
    assert '<textarea name="bio" id="signup-bio">hi &lt;b&gt;</textarea>' in html
    assert page.done.value == ""


def test_valid_submit_runs_handler(page):
    _render(page)
    _submit(page, VALID)
    assert page.done.value == "a@b.co"


def test_disabled_fields_are_server_owned(page):
    _render(page)
    assert page.signup._owned == {"note"}
    _submit(page, {**VALID, "note": "forged"})
    assert page.signup.value.note is None


def test_fields_the_page_never_rendered_keep_their_value(tmp_path):
    src = """---
from pydantic import BaseModel
from pywire import form

class Profile(BaseModel):
    name: str
    role: str = "user"
    note: str = ""

profile = form(Profile, initial={"role": "editor"})
show = wire(False)
got = wire(None)

def save(data: Profile):
    got.value = data
---
<form $bind={profile} @submit={save}>
  <input $bind={profile.name}>
  <div $if={show}><input $bind={profile.note}></div>
</form>
"""
    p = _page(_load(tmp_path, src))
    _render(p)
    forged = {"name": "Al", "role": "admin", "note": "hi"}
    asyncio.run(p.handle_event("_handler_0", {"formData": forged}))
    assert (p.got.value.role, p.got.value.note) == ("editor", "")
    # Once rendered, a field is read.
    p.show.value = True
    asyncio.run(p.render_update())
    asyncio.run(p.handle_event("_handler_0", {"formData": forged}))
    assert (p.got.value.role, p.got.value.note) == ("editor", "hi")


def test_bind_on_other_tags_is_a_compile_error(tmp_path):
    src = (
        "---" + MODEL + "signup = form(Signup)\n---\n<div $bind={signup.email}></div>\n"
    )
    with pytest.raises(PyWireSyntaxError, match="works on <form>"):
        _load(tmp_path, src)


def test_bound_form_must_be_page_level(tmp_path):
    src = (
        "---" + MODEL + "forms = [form(Signup)]\n---\n"
        "{$for f in forms}<form $bind={f}></form>{/for}\n"
    )
    with pytest.raises(PyWireSyntaxError, match="is a \\$for loop variable"):
        _load(tmp_path, src)
    # Also when the loop variable shadows a page-level form.
    src = (
        "---" + MODEL + "forms = [form(Signup)]\nf = form(Signup)\n---\n"
        "{$for f in forms}<form $bind={f}></form>{/for}\n"
    )
    with pytest.raises(PyWireSyntaxError, match="is a \\$for loop variable"):
        _load(tmp_path, src)


def test_generated_handler_names_are_reserved(tmp_path):
    src = (
        "---" + MODEL + "signup = form(Signup)\n"
        "def _handler_0(event=None):\n    pass\n---\n"
        "<form $bind={signup}></form>\n"
    )
    with pytest.raises(PyWireSyntaxError, match="reserved for the event handlers"):
        _load(tmp_path, src)


def test_bound_submit_handler_cannot_be_wired_elsewhere(tmp_path):
    src = (
        "---" + MODEL + "signup = form(Signup)\ndef save(data):\n    pass\n---\n"
        "<form $bind={signup} @submit={save}></form>\n"
        "<button @click={save}>Save</button>\n"
    )
    with pytest.raises(PyWireSyntaxError, match="only ever gets a validated model"):
        _load(tmp_path, src)


def test_bound_submit_takes_a_function_name(tmp_path):
    src = (
        "---" + MODEL + "signup = form(Signup)\ndef save(x):\n    pass\n---\n"
        "<form $bind={signup} @submit={save(1)}></form>\n"
    )
    with pytest.raises(PyWireSyntaxError, match="takes a function name"):
        _load(tmp_path, src)


def test_bound_form_without_submit_still_validates(tmp_path):
    src = (
        "---" + MODEL + "signup = form(Signup)\n---\n"
        "<form $bind={signup}><input $bind={signup.email}></form>\n"
    )
    p = _page(_load(tmp_path, src))
    html = _render(p)
    assert 'data-on-submit="_handler_0"' in html
    asyncio.run(p.handle_event("_handler_0", {"formData": {"email": "x"}}))
    assert p.signup.email.error == "Enter a valid email address"


@pytest.mark.parametrize(
    "markup,message",
    [
        ("<input $bind={signup}>", "not the whole form"),
        ("<input $bind={signup.plan}>", "is a choice"),
        ("<input $bind={done}>", "expects a form field"),
        ('<input type="radio" $bind={signup.plan}>', "needs a value="),
    ],
)
def test_bind_mistakes_are_explained(tmp_path, markup, message):
    src = "---" + MODEL + 'signup = form(Signup)\ndone = "x"\n---\n' + markup + "\n"
    p = _page(_load(tmp_path, src))
    with pytest.raises(BindError, match=message):
        _render(p)


def test_constraint_that_disagrees_with_the_model(tmp_path):
    src = (
        "---" + MODEL + "signup = form(Signup)\n---\n"
        '<input $bind={signup.name} minlength="5">\n'
    )
    p = _page(_load(tmp_path, src))
    p._is_debug = lambda: True  # dev mode: a loud error
    with pytest.raises(BindError, match="disagrees with the model"):
        _render(p)
    p._is_debug = lambda: False  # production: the model wins
    assert 'minlength="2"' in _render(p)


def test_password_input_on_a_plain_str_field(tmp_path):
    src = (
        "---" + MODEL + "signup = form(Signup)\n---\n"
        '<input type="password" $bind={signup.name}>\n'
    )
    p = _page(_load(tmp_path, src))
    p._is_debug = lambda: True
    with pytest.raises(BindError, match="Type it SecretStr"):
        _render(p)


def test_bind_on_a_component_is_a_compile_error(tmp_path, monkeypatch):
    from pywire.runtime.importer import install_import_hook

    install_import_hook()
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "bind_child.wire").write_text("<input>\n")
    src = (
        "---" + MODEL + "from bind_child import BindChild\nsignup = form(Signup)\n---\n"
        "<BindChild $bind={signup.email} />\n"
    )
    try:
        with pytest.raises(PyWireSyntaxError, match="can't go on a component"):
            _load(tmp_path, src)
    finally:
        sys.modules.pop("bind_child", None)


CHILD = (
    "---"
    + MODEL
    + """
signup = form(Signup)
saved = wire("")

def create(data: Signup):
    saved.value = data.name
---
<form $bind={signup} @submit={create}>
  <input $bind={signup.email}><input $bind={signup.name}>
  <input $bind={signup.age}><input $bind={signup.terms}>
</form>
"""
)


def test_bound_submit_can_be_a_callback_prop(tmp_path, monkeypatch):
    from pywire.runtime.importer import install_import_hook

    install_import_hook()
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "save_box.wire").write_text(
        "---"
        + MODEL
        + """
from typing import Optional
from pywire import EventHandler, props

@props
class Props:
    on_save: Optional[EventHandler] = None

signup = form(Signup)
---
<form $bind={signup} @submit={on_save}>
  <input $bind={signup.email}><input $bind={signup.name}>
  <input $bind={signup.age}><input $bind={signup.terms}>
</form>
"""
    )
    parent = """---
from save_box import SaveBox
got = wire("")

def saved(data):
    got.value = data.name
---
<SaveBox on_save={saved} />
"""
    try:
        p = _page(_load(tmp_path, parent, "parent"))
        html = _render(p)
        handler = re.search(r'data-on-submit="([^"]+)"', html).group(1)
        asyncio.run(p.handle_event(handler, {"formData": VALID}))
        assert p.got.value == "Al"
    finally:
        sys.modules.pop("save_box", None)


def test_bound_form_inside_a_component(tmp_path, monkeypatch):
    from pywire.runtime.importer import install_import_hook

    install_import_hook()
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "signup_box.wire").write_text(CHILD)
    parent = (
        "---\nfrom signup_box import SignupBox\n---\n<SignupBox />\n<SignupBox />\n"
    )
    try:
        p = _page(_load(tmp_path, parent, "parent"))
        html = _render(p)
        handlers = re.findall(r'name="__pywire_handler" value="([^"]+)"', html)
        assert len(handlers) == 2 and all(h.startswith("_comp:") for h in handlers)
        ids = re.findall(r'<form[^>]* id="([^"]+)"', html)
        assert len(set(ids)) == 2, "each instance gets its own DOM ids"
        asyncio.run(p.handle_event(handlers[1], {"formData": {**VALID, "name": "Zed"}}))
        first, second = p._components.values()
        assert (first.saved.value, second.saved.value) == ("", "Zed")
    finally:
        sys.modules.pop("signup_box", None)
