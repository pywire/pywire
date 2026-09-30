"""``$bind`` on a plain wire: the element shows the wire, editing writes it."""

import asyncio
import re

import pytest
from starlette.requests import Request

from pywire.runtime.bind import BindError
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
search = wire("")
count = wire(3)
agree = wire(False)
colors = wire(["red"])
size = wire("m")
sizes = wire(["s"])
bio = wire("hi <b>")
---
<input $bind={search} placeholder="Search">
<p id="echo">{search}</p>
<input $bind={count}>
<input $bind={agree}>
<input type="checkbox" value="red" $bind={colors}>
<input type="checkbox" value="blue" $bind={colors}>
<input type="radio" value="s" $bind={size}>
<input type="radio" value="m" $bind={size}>
<select $bind={size}><option value="s">S</option><option value="m">M</option></select>
<select $bind={sizes}><option value="s">S</option><option value="m">M</option></select>
<textarea $bind={bio}></textarea>
"""


def _load(tmp_path, source):
    f = tmp_path / "page.wire"
    f.write_text(source)
    cls = PageLoader().load(f, use_cache=False)
    return cls(request=Request(_SCOPE), params={}, query={}, path={"main": True})


def _render(page) -> str:
    return asyncio.run(page.render()).body.decode()


def _tag(html: str, pattern: str) -> str:
    match = re.search(pattern, html)
    assert match is not None, f"{pattern!r} not in {html}"
    return match.group(0)


def _checked(tag: str) -> bool:
    return re.search(r"\s(checked|selected)(\s|>|=)", tag) is not None


def _handler(tag: str, event: str) -> str:
    return _tag(tag, rf'data-on-{event}="([^"]+)"').split('"')[1]


@pytest.fixture()
def page(tmp_path):
    return _load(tmp_path, PAGE)


def test_elements_show_the_wires(page):
    html = _render(page)
    query = _tag(html, r'<input[^>]*placeholder="Search"[^>]*>')
    assert 'type="text"' in query and 'value=""' in query
    assert 'data-pw-fields-input="value,checked,values,inputType"' in query
    assert 'type="number"' in _tag(html, r'<input[^>]*value="3"[^>]*>')
    agree = _tag(html, r'<input[^>]*type="checkbox"(?![^>]*value=)[^>]*>')
    assert not _checked(agree)
    assert _checked(_tag(html, r'<input[^>]*value="red"[^>]*>'))
    assert not _checked(_tag(html, r'<input[^>]*value="blue"[^>]*>'))
    assert _checked(_tag(html, r'<input[^>]*type="radio"[^>]*value="m"[^>]*>'))
    assert not _checked(_tag(html, r'<input[^>]*type="radio"[^>]*value="s"[^>]*>'))
    assert re.search(r'<option value="m" selected>M</option>', html)
    assert "<select multiple" in html or re.search(r"<select[^>]*multiple", html)
    assert "<textarea" in html and "hi &lt;b&gt;</textarea>" in html


def test_bind_handlers_are_the_only_new_entry_points(page):
    names = type(page).__event_handlers__
    assert {n for n in names if n.startswith("_handle_bind_")} == {
        f"_handle_bind_{i}" for i in range(10)
    }


def _send(page, html, pattern, event, **data):
    name = _handler(_tag(html, pattern), event)
    asyncio.run(page.handle_event(name, {"type": event, **data}))


def test_typing_writes_the_wire(page):
    html = _render(page)
    _send(page, html, r'<input[^>]*placeholder="Search"[^>]*>', "input", value="abc")
    assert page.search.value == "abc"
    assert re.search(r'<p id="echo"[^>]*>abc</p>', _render(page))


def test_numbers_are_coerced(page):
    html = _render(page)
    number = r'<input[^>]*type="number"[^>]*>'
    _send(page, html, number, "input", value="12")
    assert page.count.value == 12
    _send(page, html, number, "input", value="")
    assert page.count.value == 12  # not a number: the wire keeps its value


def test_checkboxes_and_radios(page):
    html = _render(page)
    lone = r'<input[^>]*type="checkbox"(?![^>]*value=)[^>]*>'
    _send(page, html, lone, "change", checked=True, inputType="checkbox")
    assert page.agree.value is True
    blue = r'<input[^>]*value="blue"[^>]*>'
    _send(page, html, blue, "change", value="blue", checked=True, inputType="checkbox")
    assert list(page.colors) == ["red", "blue"]
    red = r'<input[^>]*value="red"[^>]*>'
    _send(page, html, red, "change", value="red", checked=False, inputType="checkbox")
    assert list(page.colors) == ["blue"]
    radio = r'<input[^>]*type="radio"[^>]*value="s"[^>]*>'
    _send(page, html, radio, "change", value="s", checked=True, inputType="radio")
    assert page.size.value == "s"


def test_selects_and_textarea(page):
    html = _render(page)
    multi = r"<select[^>]*multiple[^>]*>"
    _send(page, html, multi, "change", value="s", values=["s", "m"])
    assert list(page.sizes) == ["s", "m"]
    _send(page, html, r"<textarea[^>]*>", "input", value="new")
    assert page.bio.value == "new"


@pytest.mark.parametrize(
    "markup,message",
    [
        ("<input $bind={search} @input={noop}>", "already handles input"),
        ('<input $bind={search} value="x">', "the wire is the value"),
        ('<input type="checkbox" $bind={colors}>', "needs a value="),
        ("<select $bind={search}></select>", "<option>s written out"),
        ("{$for q in [search]}<input $bind={q}>{/for}", "by its name"),
        ("{$for search in [search]}<input $bind={search}>{/for}", "by its own name"),
    ],
)
def test_mistakes_are_explained(tmp_path, markup, message):
    src = '---\nsearch = wire("")\ncolors = wire([])\ndef noop():\n    pass\n---\n'
    page = _load(tmp_path, src + markup + "\n")
    with pytest.raises(BindError, match=message):
        _render(page)


GUARDED = """---
import datetime, decimal, enum

class Role(enum.Enum):
    USER = "user"
    ADMIN = "admin"

is_admin = False
role = wire(Role.USER)
plan = wire("free")
note = wire("n")
ratio = wire(1.0)
price = wire(decimal.Decimal("9.99"))
day = wire(datetime.date(2026, 1, 1))
secret = wire("s")
---
<select id="role" $bind={role}><option value="user">User</option><option value="admin">Admin</option></select>
<select id="plan" $bind={plan} disabled={not is_admin}><option value="free">Free</option></select>
<select id="pick" $bind={plan}><option value="free">Free</option><option value="pro">Pro</option></select>
<input id="note" $bind={note} readonly>
<input id="ratio" $if={is_admin} $bind={ratio}>
<input id="price" $bind={price}>
<input id="day" type="date" $bind={day}>
<input id="secret" type="hidden" $bind={secret}>
"""


def test_only_what_the_page_rendered_editable_is_written(tmp_path):
    page = _load(tmp_path, GUARDED)
    html = _render(page)
    _send(page, html, r'<select[^>]*id="plan"[^>]*>', "change", value="enterprise")
    _send(page, html, r'<input[^>]*id="note"[^>]*>', "input", value="forged")
    _send(page, html, r'<input[^>]*id="secret"[^>]*>', "change", value="x")
    assert (page.plan.value, page.note.value, page.secret.value) == ("free", "n", "s")

    # The $if never rendered its box, so its handler takes nothing.
    names = sorted(n for n in type(page).__event_handlers__ if "_bind_" in n)
    shown = set(re.findall(r'data-on-\w+="([^"]+)"', html))
    for hidden in set(names) - shown:
        asyncio.run(page.handle_event(hidden, {"type": "input", "value": "2"}))
    assert page.ratio.value == 1.0

    # A select takes only the options it offered.
    pick = r'<select[^>]*id="pick"[^>]*>'
    _send(page, html, pick, "change", value="enterprise")
    assert page.plan.value == "free"
    _send(page, html, pick, "change", value="pro")
    assert page.plan.value == "pro"


HIDES = """---
open = wire(True)
name = wire("a")

def close():
    open.value = False
---
<div id="box">
  <input id="name" $if={open} $bind={name}>
</div>
<button id="close" @click={close}>x</button>
"""


def test_an_element_hidden_later_stops_taking_writes(tmp_path):
    page = _load(tmp_path, HIDES)
    html = _render(page)
    name = _handler(_tag(html, r'<input[^>]*id="name"[^>]*>'), "input")
    asyncio.run(page.handle_event(name, {"type": "input", "value": "b"}))
    assert page.name.value == "b"

    # The box goes away in a partial update, as over a live connection.
    close = _handler(_tag(html, r'<button[^>]*id="close"[^>]*>'), "click")
    update = asyncio.run(page.handle_event(close, {"type": "click"}))
    assert 'id="name"' not in str(update)
    assert isinstance(update, dict) and update.get("type") == "regions", update
    asyncio.run(page.handle_event(name, {"type": "input", "value": "forged"}))
    assert page.name.value == "b"


def test_wires_keep_their_type(tmp_path):
    page = _load(tmp_path, GUARDED)
    html = _render(page)
    assert re.search(r'<option value="user" selected>', html)
    role = r'<select[^>]*id="role"[^>]*>'
    _send(page, html, role, "change", value="admin")
    assert page.role.value is type(page.role.value).ADMIN

    price = r'<input[^>]*id="price"[^>]*>'
    for bad in ("NaN", "sNaN", "Infinity", "abc"):
        _send(page, html, price, "input", value=bad)
    assert str(page.price.value) == "9.99"
    _send(page, html, price, "input", value="12.50")
    assert str(page.price.value) == "12.50"

    day = r'<input[^>]*id="day"[^>]*>'
    _send(page, html, day, "change", value="2026-02-03")
    assert page.day.value.isoformat() == "2026-02-03"
    _send(page, html, day, "change", value="not a date")
    assert page.day.value.isoformat() == "2026-02-03"
