"""Field specs: HTML attributes derived from the model's JSON schema."""

from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal, Optional

import pytest
from pydantic import BaseModel, EmailStr, Field, HttpUrl, SecretStr
from pydantic.json_schema import SkipJsonSchema

from pywire import form
from pywire.forms.schema import html_pattern, humanize, root_spec
from pywire.forms import Upload, UploadField


class Plan(str, Enum):
    FREE = "free"
    PRO = "pro"


class Size(Enum):
    SMALL = 1
    LARGE = 2


class Address(BaseModel):
    street: str = Field(min_length=1)
    zip: Optional[str] = None


class Item(BaseModel):
    name: str
    qty: int = Field(1, ge=1)


class Everything(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2, max_length=50, title="Your name")
    bio: str = Field("", description="A few words")
    age: int = Field(ge=13, lt=120)
    price: Decimal = Field(gt=0, multiple_of=Decimal("0.01"))
    ratio: float = Field(ge=0, le=1)
    small: Annotated[int, Field(gt=0, lt=10)] = 1
    plan: Literal["free", "pro"] = "free"
    plan2: Plan
    size: Size = Size.SMALL
    only: Literal["x"] = "x"
    tags: list[str] = []
    colors: list[Literal["red", "blue"]] = Field(default_factory=list, max_length=2)
    terms: Literal[True]
    news: bool = False
    pw: SecretStr = Field(min_length=12)
    site: Optional[HttpUrl] = None
    born: date
    at: datetime
    t: time
    addr: Address
    items: list[Item] = Field(default_factory=list, max_length=5)
    alias_f: str = Field("", alias="aliasF")
    code: str = Field(pattern=r"^[A-Z]{3}$")
    loose: str = Field("", pattern=r"[a-z]+")
    maybe_int: Optional[int] = None
    avatar: Optional[Upload] = None
    docs: list[Upload] = []
    photo: Annotated[
        Upload, UploadField(max_size="1 MiB", accept=["image/png", ".JPG"])
    ]
    papers: Annotated[list[Upload], UploadField(max_files=3, max_size=1000)] = []
    secret_server_side: SkipJsonSchema[str] = "server"


SPEC = root_spec(Everything)
C = SPEC.children


def test_text_constraints_and_label():
    name = C["name"]
    assert (name.kind, name.input_type, name.required) == ("text", "text", True)
    assert name.attrs == {"minlength": "2", "maxlength": "50"}
    assert name.label == "Your name"
    assert C["bio"].description == "A few words"
    assert C["bio"].required is False


def test_formats_pick_input_types():
    assert C["email"].input_type == "email"
    assert C["site"].input_type == "url"
    assert C["site"].required is False  # Optional
    assert (C["pw"].kind, C["pw"].input_type) == ("secret", "password")
    assert C["born"].input_type == "date"
    assert C["at"].input_type == "datetime-local"
    assert C["t"].input_type == "time"


def test_integer_bounds():
    age = C["age"]
    assert age.input_type == "number"
    # lt=120 on an int is max=119 in HTML
    assert age.attrs == {"min": "13", "max": "119", "inputmode": "numeric"}
    assert C["small"].attrs == {"min": "1", "max": "9", "inputmode": "numeric"}


def test_float_and_decimal_steps():
    assert C["ratio"].attrs == {
        "min": "0",
        "max": "1",
        "step": "any",
        "inputmode": "decimal",
    }
    # gt=0 on a decimal can't be said in HTML: no min, but the step stays
    assert C["price"].attrs == {"step": "0.01", "inputmode": "decimal"}
    assert C["price"].required is True


def test_choices_from_literal_and_enum():
    assert [(o.value, o.label) for o in C["plan"].options] == [
        ("free", "Free"),
        ("pro", "Pro"),
    ]
    assert C["plan"].required is False  # has a default
    assert [o.value for o in C["plan2"].options] == ["free", "pro"]
    assert C["plan2"].required is True
    assert [(o.value, o.label) for o in C["size"].options] == [
        ("1", "Small"),
        ("2", "Large"),
    ]
    assert [o.value for o in C["only"].options] == ["x"]


def test_lists():
    assert C["tags"].kind == "multi"
    colors = C["colors"]
    assert colors.kind == "multichoice"
    assert [o.value for o in colors.options] == ["red", "blue"]
    assert colors.max_items == 2
    items = C["items"]
    assert items.kind == "list" and items.max_items == 5
    assert items.item is not None and set(items.item.children) == {"name", "qty"}


def test_booleans():
    assert (C["news"].kind, C["news"].required) == ("boolean", False)
    # Literal[True]: a box that must be ticked
    assert (C["terms"].kind, C["terms"].required) == ("boolean", True)


def test_nested_and_alias_and_skip():
    addr = C["addr"]
    assert addr.kind == "model"
    assert addr.children["street"].required is True
    assert addr.children["zip"].required is False
    assert C["alias_f"].data_key == "aliasF"
    assert "secret_server_side" not in C


def test_files():
    assert (C["avatar"].kind, C["avatar"].required) == ("file", False)
    assert C["docs"].kind == "files"
    assert C["photo"].required
    assert C["photo"].attrs == {
        "accept": "image/png,.jpg",
        "data-pw-max-size": str(1024 * 1024),
    }
    assert C["papers"].max_items == 3
    assert C["papers"].attrs == {"data-pw-max-size": "1000"}


def test_pattern_only_when_anchored():
    assert C["code"].attrs["pattern"] == "[A-Z]{3}"
    # Pydantic searches; HTML matches the whole value. Unanchored differs.
    assert "pattern" not in C["loose"].attrs


@pytest.mark.parametrize(
    "pattern,expected",
    [
        (r"^[a-z]+$", "[a-z]+"),
        (r"^\d{3}-\d{4}$", r"\d{3}-\d{4}"),
        (r"^[a-z-]+$", None),  # trailing '-' in a class breaks the v flag
        (r"^[a-z(]+$", None),
        (r"^(?P<x>a)$", None),  # Python-only group
        (r"^\Aabc$", None),
        (r"abc", None),
        (r"^abc\$", None),  # escaped $, not an anchor
    ],
)
def test_html_pattern(pattern, expected):
    assert html_pattern(pattern) == expected


def test_humanize_is_sentence_case():
    assert humanize("first_name") == "First name"
    assert humanize("51+") == "51+"


def test_form_rejects_non_models():
    with pytest.raises(TypeError, match="Pydantic model"):
        form(dict)  # type: ignore[arg-type]


def test_specs_are_cached_per_model():
    assert root_spec(Everything).model is root_spec(Everything).model


def test_self_referencing_model():
    class Node(BaseModel):
        label: str
        children: list["Node"] = []

    Node.model_rebuild()
    f = form(Node)
    row = f.children[0]
    assert row.fields.label.html_name == "children.0.label"
    assert row.children[1].fields.label.html_name == "children.0.children.1.label"
