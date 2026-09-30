"""Handlers get server-signed call arguments and declared event fields only.

``{$for it in items}<button @click={delete(it["id"])}>`` must not let a client
delete an id it was never shown, and ``def rename(name, is_admin=False)``
must not take ``is_admin`` from the event data.
"""

import asyncio
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import msgpack
import pytest
from starlette.requests import Request
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire
from pywire.runtime.handler_args import HandlerArgsError, sign_args
from pywire.runtime.loader import PageLoader
from pywire.runtime.protocol import ClientMessageError, unpack_client_message

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
items = wire([{"id": 1}, {"id": 2}])
deleted = []
renamed = []
searched = []
extras = []

def delete(item_id):
    deleted.append(item_id)

def rename(name, is_admin=False):
    renamed.append((name, is_admin))

def search(value):
    searched.append(value)

def everything(**fields):
    extras.append(fields)
---
{$for it in items}<button @click={delete(it["id"])}>x</button>{/for}
<input name="n" @change={rename}>
<input @input={search}>
<input @keyup={everything}>
<p @mouseover.stop={search} @mouseover.prevent.once={everything}>hover</p>
"""

OTHER = """---
seen = []

def view(item_id):
    seen.append(item_id)
---
<button @click={view(42)}>view</button>
"""


def _load(tmp_path: Path, source: str, name: str) -> Any:
    f = tmp_path / name
    f.write_text(source)
    cls = PageLoader().load(f, use_cache=False)
    return cls(request=Request(_SCOPE), params={}, query={}, path={"main": True})


def _tokens(html: str) -> list[str]:
    return re.findall(r'data-pw-args-click="([^"]+)"', html)


@pytest.fixture
def page(tmp_path: Path) -> Any:
    return _load(tmp_path, PAGE, "page.wire")


def test_rendered_args_reach_the_handler(page: Any) -> None:
    html = asyncio.run(page.render()).body.decode()
    first, second = _tokens(html)
    assert "data-arg" not in html
    asyncio.run(page.handle_event("_handler_0", {"type": "click", "args": second}))
    asyncio.run(page.handle_event("_handler_0", {"type": "click", "args": first}))
    assert page.deleted == [2, 1]


@pytest.mark.parametrize(
    "forged",
    [
        {"arg0": 999},
        {"arg-0": 999},
        [999],
        "Wzk5OV0",
        "Wzk5OV0.AAAAAAAAAAAAAAAAAAAAAA",
        999,
    ],
)
def test_client_chosen_args_are_refused(page: Any, forged: Any) -> None:
    asyncio.run(page.render())
    with pytest.raises(HandlerArgsError):
        asyncio.run(page.handle_event("_handler_0", {"type": "click", "args": forged}))
    assert page.deleted == []


def test_a_changed_value_is_refused(page: Any) -> None:
    token = _tokens(asyncio.run(page.render()).body.decode())[0]
    body, tag = token.split(".")
    tampered = f"{sign_args(page, '_handler_0', 999).split('.')[0]}.{tag}"
    with pytest.raises(HandlerArgsError):
        asyncio.run(page._dispatch_handler("_handler_0", {"args": tampered}))
    assert page.deleted == []


def test_args_are_bound_to_their_page_and_handler(tmp_path: Path) -> None:
    page = _load(tmp_path, PAGE, "page.wire")
    other = _load(tmp_path, OTHER, "other.wire")
    token = _tokens(asyncio.run(other.render()).body.decode())[0]
    # Same generated name (_handler_0), different page: refused.
    with pytest.raises(HandlerArgsError):
        asyncio.run(page._dispatch_handler("_handler_0", {"args": token}))
    # Signed for another handler of the same page: refused.
    with pytest.raises(HandlerArgsError):
        asyncio.run(
            page._dispatch_handler(
                "_handler_0", {"args": sign_args(page, "_handler_1", 1)}
            )
        )
    asyncio.run(other._dispatch_handler("_handler_0", {"args": token}))
    assert page.deleted == [] and other.seen == [42]


def test_event_data_never_fills_other_parameters(page: Any) -> None:
    asyncio.run(
        page.handle_event(
            "rename", {"type": "change", "name": "n", "is_admin": True, "value": "x"}
        )
    )
    assert page.renamed == [("n", False)]


def test_declared_event_fields_bind_by_name(page: Any) -> None:
    asyncio.run(page.handle_event("search", {"type": "input", "value": "hello"}))
    assert page.searched == ["hello"]
    asyncio.run(
        page.handle_event(
            "everything",
            {"type": "keyup", "key": "a", "shiftKey": True, "is_admin": True},
        )
    )
    assert page.extras == [{"type": "keyup", "key": "a", "shift_key": True}]


def test_args_verify_across_processes_of_one_app(tmp_path: Path) -> None:
    """Two processes serving the app accept each other's rendered args:
    the scope digest must not depend on hash randomization."""
    (tmp_path / "page.wire").write_text(PAGE)
    script = (
        "import sys, pathlib; from pywire.runtime.loader import PageLoader; "
        "page = pathlib.Path(sys.argv[1]); "
        "print(PageLoader().load(page, use_cache=False).__pw_scope__)"
    )
    scopes = set()
    for seed in ("1", "2", "3"):
        out = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path / "page.wire")],
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        )
        scopes.add(out.stdout.strip())
    assert len(scopes) == 1


def test_signing_key_comes_from_the_app_secret(tmp_path: Path) -> None:
    pages = tmp_path / "pages"
    pages.mkdir()
    secret = "k" * 32
    first = PyWire(pages_dir=str(pages), secret_key=secret)
    second = PyWire(pages_dir=str(pages), secret_key=secret)
    assert first._handler_args_key() == second._handler_args_key()
    assert first._handler_args_key() != secret.encode()
    assert PyWire(pages_dir=str(pages), secret_key="x" * 32)._handler_args_key() != (
        first._handler_args_key()
    )


@pytest.mark.parametrize(
    "value",
    [
        msgpack.ExtType(5, b"x"),
        msgpack.Timestamp(1, 0),
        datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc),
    ],
)
def test_client_messages_are_plain_data(value: Any) -> None:
    raw = msgpack.packb({"data": {"items": [1, {"v": value}]}}, datetime=True)
    with pytest.raises(ClientMessageError):
        unpack_client_message(raw)


def test_plain_client_message_decodes() -> None:
    message = {"type": "event", "data": {"v": [1, 2.5, "x", None, True, b"b"]}}
    assert unpack_client_message(msgpack.packb(message)) == message


def test_stateless_endpoint_refuses_extension_types(tmp_path: Path) -> None:
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.wire").write_text(OTHER)
    app = PyWire(pages_dir=str(pages), stateless=True, secret_key="s" * 32)
    with TestClient(app) as client:
        html = client.get("/").text
        snapshot = html.split('_pywire_snapshot" type="text/plain">')[1].split(
            "</script>"
        )[0]

        def post(data: Any) -> Any:
            return client.post(
                "/_pywire/stateless",
                content=msgpack.packb(
                    {
                        "path": "/",
                        "handler": "_handler_0",
                        "data": data,
                        "snapshot": snapshot,
                    }
                ),
                headers={"Content-Type": "application/x-msgpack"},
            )

        assert post({"type": "click", "x": msgpack.ExtType(1, b"")}).status_code == 400
        # The token the page rendered works over this transport too.
        token = _tokens(html)[0]
        assert post({"type": "click", "args": token}).status_code == 200
        assert post({"type": "click", "args": {"arg0": 7}}).status_code == 500
