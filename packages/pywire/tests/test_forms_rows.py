"""List fields: add and remove rows with submit buttons, keeping what was typed."""

import asyncio
import re
import shutil
import tempfile
from pathlib import Path

import pytest
from pydantic import BaseModel, Field
from starlette.testclient import TestClient

from pywire import form
from pywire.forms.form import ACTION, STATE
from pywire.runtime.app import PyWire


class Item(BaseModel):
    name: str = Field(min_length=1)
    qty: int = 1


class Order(BaseModel):
    customer: str
    items: list[Item] = Field(default_factory=list, max_length=3)


def act(f, data, handler=None):
    """Submit ``data`` as if the page had rendered every posted field."""
    f._editable.update(n for n in data if n != ACTION and n not in f._owned)
    asyncio.run(f._pw_submit(None, handler, {"formData": data}))


def test_buttons_are_submit_buttons_that_skip_validation():
    f = form(Order, initial={"customer": "A", "items": [{"name": "x"}]})
    assert f.items.add_button == {
        "type": "submit",
        "name": ACTION,
        "value": "add:items",
        "formnovalidate": True,
    }
    assert f.items[0].remove_button["value"] == "remove:items.0"
    with pytest.raises(TypeError):
        f.customer.add_button  # noqa: B018
    with pytest.raises(TypeError):
        f.items.remove_button  # noqa: B018


def test_add_keeps_what_was_typed():
    got = []
    f = form(Order)
    assert len(f.items) == 0
    act(f, {"customer": "Ann", ACTION: "add:items"})
    assert len(f.items) == 1
    assert f.customer.raw == "Ann"
    act(f, {"customer": "Ann", "items.0.name": "pen", ACTION: "add:items"})
    assert len(f.items) == 2
    assert f.items[0].name.raw == "pen"
    assert f.items[1].name.raw == ""
    assert not f.submitted and f.errors == {}

    # A real submit reads the rows the form rendered.
    act(
        f,
        {
            "customer": "Ann",
            "items.0.name": "pen",
            "items.1.name": "ink",
            "items.1.qty": "2",
        },
        handler=got.append,
    )
    assert [(i.name, i.qty) for i in got[0].items] == [("pen", 1), ("ink", 2)]


def test_add_stops_at_max_length():
    f = form(Order)
    for _ in range(5):
        rows = {f"items.{i}.name": "x" for i in range(len(f.items))}
        act(f, {"customer": "A", **rows, ACTION: "add:items"})
    assert len(f.items) == 3


def test_remove_shifts_the_rows_after_it():
    f = form(Order)
    rows = {f"items.{i}.name": n for i, n in enumerate(["a", "", "c"])}
    act(f, {"customer": "A", **rows})  # a submit: row 1 is invalid
    assert f.errors == {"items.1.name": "This field is required"}

    act(f, {"customer": "A", **rows, ACTION: "remove:items.0"})
    assert len(f.items) == 2
    assert [f.items[i].name.raw for i in range(2)] == ["", "c"]
    assert f.errors == {"items.0.name": "This field is required"}

    act(
        f,
        {
            "customer": "A",
            "items.0.name": "",
            "items.1.name": "c",
            ACTION: "remove:items.0",
        },
    )
    assert [r.name.raw for r in f.items] == ["c"]
    assert f.errors == {}


@pytest.mark.parametrize(
    "action",
    [
        "add:customer",
        "add:nope",
        "remove:items.9",
        "remove:items.x",
        "remove:customer.0",
        "jump:items",
        "",
    ],
)
def test_unknown_actions_change_nothing(action):
    f = form(Order)
    act(f, {"customer": "A", "items.0.name": "a", ACTION: action})
    assert len(f.items) == 1
    assert f.customer.raw == "A"
    assert not f.submitted


def test_row_counts_survive_a_snapshot():
    f = form(Order)
    act(f, {"customer": "A", ACTION: "add:items"})
    g = form(Order)
    g.__pw_restore__(f.__pw_snapshot__())
    assert len(g.items) == 1
    g.__pw_restore__({**f.__pw_snapshot__(), "rows": {"items": 10**9}})
    assert len(g.items) == 0


PAGE = """---
from pydantic import BaseModel, Field
from pywire import form

class Item(BaseModel):
    name: str = Field(min_length=1)

class Order(BaseModel):
    customer: str
    items: list[Item] = Field(default_factory=list, max_length=3)

order = form(Order)
done = wire("")

def create(data: Order):
    done.value = "|".join(i.name for i in data.items)
---
<form $bind={order} @submit={create}>
  <input $bind={order.customer}>
  {$for row in order.items}
    <fieldset>
      <input $bind={row.name}>
      <button {**row.remove_button}>Remove</button>
    </fieldset>
  {/for}
  <button {**order.items.add_button}>Add item</button>
  <button type="submit">Save</button>
</form>
<p id="done">{done}</p>
"""


@pytest.fixture()
def client():
    root = Path(tempfile.mkdtemp())
    pages = root / "pages"
    pages.mkdir()
    (pages / "index.wire").write_text(PAGE)
    with TestClient(PyWire(pages_dir=str(pages)), raise_server_exceptions=False) as c:
        yield c
    shutil.rmtree(root, ignore_errors=True)


def test_rows_work_without_javascript(client):
    html = client.get("/").text
    handler = re.search(r'name="__pywire_handler" value="([^"]+)"', html).group(1)
    add = re.search(r"<button[^>]*add:items[^>]*>", html).group(0)
    assert 'type="submit"' in add and "formnovalidate" in add

    r = client.post(
        "/", data={"__pywire_handler": handler, "customer": "Ann", ACTION: "add:items"}
    )
    added = r.text
    assert r.status_code == 200
    assert 'name="items.0.name"' in r.text and 'value="Ann"' in r.text

    # Without the state the page posted, the added row was never rendered by
    # this request, so it isn't read.
    r = client.post(
        "/",
        data={"__pywire_handler": handler, "customer": "Ann", "items.0.name": "pen"},
    )
    assert ">pen</p>" not in r.text

    state = re.search(rf'name="{STATE}" value="([^"]+)"', added).group(1)
    r = client.post(
        "/",
        data={
            "__pywire_handler": handler,
            STATE: state,
            "customer": "Ann",
            "items.0.name": "pen",
        },
    )
    assert r.status_code == 200
    assert '<p id="done"' in r.text and ">pen</p>" in r.text


def test_enter_submits_rather_than_adding_or_removing(client):
    html = client.get("/").text
    form = html[html.index("<form") :]
    buttons = re.findall(r"<button[^>]*>", form)
    assert "data-pw-default-submit" in buttons[0]
    assert "name=" not in buttons[0] and 'type="submit"' in buttons[0]


def test_remove_moves_rendered_names_and_nested_rows():
    class Part(BaseModel):
        sku: str = ""

    class Line(BaseModel):
        name: str = ""
        parts: list[Part] = []

    class Build(BaseModel):
        lines: list[Line] = []

    f = form(Build)
    act(f, {"lines.0.name": "a", "lines.1.name": "b", ACTION: "add:lines.1.parts"})
    assert len(f.lines[1].parts) == 1
    act(f, {"lines.0.name": "a", "lines.1.name": "b", ACTION: "remove:lines.0"})
    assert [line.name.raw for line in f.lines] == ["b"]
    assert len(f.lines[0].parts) == 1
    assert "lines.1.name" not in f._editable


def test_row_indexes_must_be_ascii_digits():
    f = form(Order)
    act(f, {"customer": "A", ACTION: "remove:items.²"})
    assert f.errors == {}
