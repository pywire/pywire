"""Non-interactive mode keeps each page's state apart, per user (H4).

The session holds one record per page (class and path). A page never
restores another page's record, a record saved for one user never restores
for another, and the user always comes from the request.
"""

from pathlib import Path
from typing import Any, Dict

import pytest
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire

PAGE = """!path "/{name}"
---
note = wire("default-{name}")

def save(data):
    note.value = data["text"]
---
<p id="note">[{{note}}]</p>
<p id="user">user={{user}}</p>
<form method="post" @submit={{save}}><input name="text"><button>save</button></form>
"""

_CURRENT: Dict[str, Any] = {"user": None}


class _App(PyWire):
    def get_user(self, request_or_websocket: Any) -> Any:
        return _CURRENT["user"]


@pytest.fixture
def client(tmp_path: Path):
    pages = tmp_path / "pages"
    pages.mkdir()
    for name in ("a", "b"):
        (pages / f"{name}.wire").write_text(PAGE.format(name=name))
    _CURRENT["user"] = None
    app = _App(pages_dir=str(pages), interactive_server_mode=False)
    return TestClient(app)


def _save(client: TestClient, path: str, text: str) -> None:
    r = client.post(path, data={"__pywire_handler": "save", "text": text})
    assert r.status_code == 200, r.text
    assert f"[{text}]" in r.text


def test_pages_keep_their_own_state(client: TestClient) -> None:
    _save(client, "/a", "secret-A")
    # Same session, another page with a wire of the same name.
    assert "[default-b]" in client.get("/b").text
    _save(client, "/b", "value-B")
    # Visiting /b did not drop /a's state, nor overwrite it.
    assert "[secret-A]" in client.get("/a").text
    assert "[value-B]" in client.get("/b").text


def test_state_is_not_restored_for_another_user(client: TestClient) -> None:
    _CURRENT["user"] = "alice"
    _save(client, "/a", "alice-draft")
    assert "[alice-draft]" in client.get("/a").text

    # Alice logs out and Bob logs in, in the same browser (same session).
    _CURRENT["user"] = "bob"
    html = client.get("/a").text
    assert "[default-a]" in html
    assert "user=bob" in html
    assert "alice" not in html

    _CURRENT["user"] = None
    html = client.get("/a").text
    assert "[default-a]" in html and "alice" not in html
