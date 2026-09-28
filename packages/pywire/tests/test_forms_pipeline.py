"""The submit pipeline: whitelist, shape, validate, act."""

import asyncio
from typing import Literal, Optional

import pytest
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from pydantic.json_schema import SkipJsonSchema

from pywire import form
from pywire.forms.form import FORM_MEMBERS, FIELD_MEMBERS
from pywire.runtime.files import FileUpload


class Address(BaseModel):
    street: str = Field(min_length=1)
    zip: Optional[str] = None


class Item(BaseModel):
    name: str
    qty: int = Field(1, ge=1)


class Signup(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2, max_length=50)
    age: int = Field(ge=13)
    plan: Literal["free", "pro"] = "free"
    terms: Literal[True]
    news: bool = False
    nickname: str = ""
    tags: list[Literal["a", "b", "c"]] = []
    addr: Optional[Address] = None
    items: list[Item] = Field(default_factory=list, max_length=3)
    password: Optional[SecretStr] = None

    @field_validator("name")
    @classmethod
    def no_bob(cls, v: str) -> str:
        if v == "bob":
            raise ValueError("Bob is not allowed")
        return v

    @model_validator(mode="after")
    def pro_is_adults(self) -> "Signup":
        if self.plan == "pro" and self.age < 18:
            raise ValueError("Pro plans are for adults")
        return self


VALID = {
    "email": "a@b.co",
    "name": "Al",
    "age": "20",
    "terms": "true",
}


class Page:
    """Stands in for BasePage: the pipeline only flags invalid submits."""


def submit(f, data, handler=None, page=None):
    page = page or Page()
    asyncio.run(f._pw_submit(page, handler, {"formData": data}))
    return page


def test_valid_submit_calls_handler_with_model():
    got = []
    f = form(Signup)
    page = submit(f, VALID, handler=got.append)
    assert not getattr(page, "_pw_form_invalid", False)
    assert f.valid and f.submitted
    (value,) = got
    assert isinstance(value, Signup)
    assert (value.age, value.news, value.tags, value.addr) == (20, False, [], None)
    assert f.value is value


def test_async_and_zero_arg_handlers():
    seen = []

    async def create(data: Signup) -> None:
        seen.append(data.name)

    def ping() -> None:
        seen.append("ping")

    f = form(Signup)
    submit(f, VALID, handler=create)
    submit(f, VALID, handler=ping)
    assert seen == ["Al", "ping"]


def test_invalid_submit_records_errors_and_skips_handler():
    called = []
    f = form(Signup)
    page = submit(
        f,
        {"email": "x", "name": "", "age": "12", "plan": "gold"},
        handler=called.append,
    )
    assert called == [] and page._pw_form_invalid is True
    assert not f.valid
    assert f.errors == {
        "email": "Enter a valid email address",
        "name": "This field is required",
        "age": "Must be 13 or more",
        "plan": "Choose one of the options",
        "terms": "Check this box to continue",
    }
    assert [e.code for e in f.age.errors] == ["rangeUnderflow"]
    assert f.email.errors[0].type == "value_error"
    # What the user typed is kept for the re-render.
    assert (f.email.raw, f.age.raw, f.age.value) == ("x", "12", 12)


def test_fields_outside_the_schema_never_reach_the_model():
    class Profile(BaseModel):
        # Even a model that accepts extras only sees its schema's fields.
        model_config = ConfigDict(extra="allow")
        name: str
        role: SkipJsonSchema[str] = "member"  # server-owned

    got = []
    f = form(Profile)
    submit(f, {"name": "Al", "role": "admin", "is_admin": "1"}, handler=got.append)
    assert got[0].role == "member"
    assert got[0].model_extra == {}
    assert f.__pw_snapshot__()["raw"] == {"name": ["Al"]}


def test_empty_text_means_not_filled_in():
    got = []
    f = form(Signup)
    # nickname has a default: an empty box is an empty string
    submit(f, {**VALID, "nickname": ""}, handler=got.append)
    assert got[-1].nickname == ""
    # Optional nested field left empty is None
    submit(f, {**VALID, "addr.street": "", "addr.zip": ""}, handler=got.append)
    assert got[-1].addr is None


def test_checkboxes_and_multi_values():
    got = []
    f = form(Signup)
    submit(f, {**VALID, "news": "true", "tags": ["a", "c"]}, handler=got.append)
    assert (got[-1].news, got[-1].tags) == (True, ["a", "c"])
    submit(f, {**VALID, "tags": ["a", "z"]})
    assert f.errors == {"tags": "Choose one of the options"}
    assert f.tags.raw == ["a", "z"]
    # A later submit without the box: unticked, not "still ticked".
    submit(f, {**VALID})
    assert (f.news.raw, f.tags.raw) == ("", [])


def test_nested_and_list_rows():
    got = []
    f = form(Signup)
    submit(
        f,
        {
            **VALID,
            "addr.street": "Main",
            "items.0.name": "x",
            "items.2.name": "z",
            "items.2.qty": "3",
            "items.x.name": "junk",
        },
        handler=got.append,
    )
    value = got[-1]
    assert value.addr == Address(street="Main")
    assert [(i.name, i.qty) for i in value.items] == [("x", 1), ("z", 3)]


def test_list_rows_are_capped():
    f = form(Signup)
    data = {**VALID, **{f"items.{i}.name": "n" for i in range(50)}}
    submit(f, data)
    assert f.errors == {"items": "Choose at most 3"}


def test_nested_errors_use_field_paths():
    f = form(Signup)
    submit(f, {**VALID, "addr.zip": "1", "items.0.qty": "0"})
    assert f.errors == {
        "addr.street": "This field is required",
        "items.0.name": "This field is required",
        "items.0.qty": "Must be 1 or more",
    }
    assert f.items[0].qty.error == "Must be 1 or more"
    assert f.addr.street.error == "This field is required"


def test_validator_messages_and_form_level_errors():
    f = form(Signup)
    submit(f, {**VALID, "name": "bob"})
    assert f.name.error == "Bob is not allowed"
    assert f.name.errors[0].code == "customError"
    submit(f, {**VALID, "plan": "pro", "age": "15"})
    assert f.errors == {}
    assert f.error == "Pro plans are for adults"
    assert not f.valid


def test_validator_message_wins_on_an_email_field():
    class Corporate(BaseModel):
        email: EmailStr

        @field_validator("email")
        @classmethod
        def corp_only(cls, v: str) -> str:
            if not v.endswith("@corp.com"):
                raise ValueError("Only @corp.com emails are allowed")
            return v

    f = form(Corporate)
    submit(f, {"email": "a@b.co"})
    assert (f.email.error, f.email.errors[0].code) == (
        "Only @corp.com emails are allowed",
        "customError",
    )
    submit(f, {"email": "bad"})
    assert (f.email.error, f.email.errors[0].code) == (
        "Enter a valid email address",
        "typeMismatch",
    )


def test_handler_can_reject_with_errors():
    f = form(Signup)

    def create(data: Signup) -> None:
        f.email.error = "That email is already registered"

    page = submit(f, VALID, handler=create)
    assert page._pw_form_invalid is True
    assert f.email.error == "That email is already registered"
    f.email.error = None
    assert f.valid


def test_messages_override():
    f = form(
        Signup,
        messages={
            "tooShort": "Too short ({min_length}+)",
            "age.rangeUnderflow": "Too young",
        },
    )
    submit(f, {**VALID, "name": "A", "age": "1"})
    assert f.name.error == "Too short (2+)"
    assert f.age.error == "Too young"


def test_context_reaches_validators():
    class Seats(BaseModel):
        seats: int

        @field_validator("seats")
        @classmethod
        def within(cls, v: int, info: ValidationInfo) -> int:
            if v > info.context["left"]:
                raise ValueError(f"Only {info.context['left']} left")
            return v

    left = {"n": 3}
    f = form(Seats, context=lambda: {"left": left["n"]})
    submit(f, {"seats": "5"})
    assert f.seats.error == "Only 3 left"
    left["n"] = 10
    submit(f, {"seats": "5"})
    assert f.valid


def test_secrets_are_never_kept_or_echoed():
    f = form(Signup)
    submit(f, {**VALID, "name": "A", "password": "hunter2hunter2"})
    assert f.password.raw == ""
    assert "password" not in f.__pw_snapshot__()["raw"]
    assert f.password.attrs.get("value") is None


def test_snapshot_roundtrip():
    f = form(Signup)
    submit(f, {"email": "x", "tags": ["a"], "name": "Al"})
    state = f.__pw_snapshot__()
    g = form(Signup)
    g.__pw_restore__(state)
    assert g.errors == f.errors
    assert (g.email.raw, g.tags.raw, g.submitted) == ("x", ["a"], True)
    assert g.email.errors[0].code == "typeMismatch"


def test_restore_ignores_names_outside_schema():
    g = form(Signup)
    g.__pw_restore__({"raw": {"is_admin": ["1"], "email": ["e"]}, "errors": "junk"})
    assert g.__pw_snapshot__()["raw"] == {"email": ["e"]}


def test_initial_values_and_load_and_reset():
    project = Signup(email="a@b.co", name="Al", age=30, terms=True, tags=["b"])
    f = form(Signup, initial=project)
    assert (f.email.raw, f.age.raw, f.tags.raw, f.terms.raw) == (
        "a@b.co",
        "30",
        ["b"],
        "true",
    )
    assert f.age.value == 30
    f.load({"email": "c@d.co", "age": 40})
    assert (f.email.raw, f.age.raw, f.plan.raw) == ("c@d.co", "40", "free")
    submit(f, {"email": "bad"})
    assert f.dirty and not f.valid
    f.reset()
    assert (f.email.raw, f.valid, f.submitted, f.dirty) == (
        "c@d.co",
        True,
        False,
        False,
    )


def test_server_owned_fields_keep_the_server_value():
    got = []
    f = form(Signup, initial={"email": "owner@b.co"})
    f._owned.add("email")  # rendered disabled/readonly
    submit(f, {**VALID, "email": "attacker@evil.co"}, handler=got.append)
    assert got[-1].email == "owner@b.co"


def test_files_only_come_from_the_server():
    class Upload(BaseModel):
        avatar: Optional[FileUpload] = None
        docs: list[FileUpload] = []

    got = []
    f = form(Upload)
    real = FileUpload("a.png", "image/png", 3, b"abc")
    submit(
        f,
        {"avatar": "data:image/png;base64,AAAA", "docs": [real, {"content": "x"}]},
        handler=got.append,
    )
    assert got[-1].avatar is None
    assert got[-1].docs == [real]


def test_unknown_upload_ids_are_ignored():
    class Upload(BaseModel):
        avatar: FileUpload

    f = form(Upload)
    submit(f, {"avatar": {"_upload_id": "../../etc/passwd"}})
    assert f.avatar.error == "Choose a file"


def test_field_lookup_and_clashes():
    f = form(Signup)
    with pytest.raises(AttributeError, match="Did you mean 'email'"):
        f.emial  # noqa: B018
    with pytest.raises(AttributeError, match="Can't assign"):
        f.email = "x"  # type: ignore[misc]
    assert f["email"] is f.email is f.fields.email
    assert [b.html_name for b in f.fields][:3] == ["email", "name", "age"]
    assert f.items[0].name.html_name == "items.0.name"
    assert f.addr.street.html_id.endswith("-addr-street")
    # Members win; names that clash stay reachable through .fields.
    assert "name" not in FIELD_MEMBERS and "id" not in FIELD_MEMBERS
    assert FORM_MEMBERS.isdisjoint({"email", "name", "age"})
