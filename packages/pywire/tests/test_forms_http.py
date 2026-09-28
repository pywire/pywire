"""Bound forms over HTTP: the same pipeline for native POSTs in every mode,
and for stateless events that carry the form state in the snapshot."""

import re
import shutil
import tempfile
from pathlib import Path

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire
from pywire.runtime.snapshot_codec import decode_snapshot

SECRET = "forms-test-secret"

PAGE = """---
from typing import Annotated, Literal, Optional
from pydantic import BaseModel, EmailStr, Field
from pywire import form
from pywire.forms import Upload, UploadField

class Signup(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2)
    tags: list[Literal["a", "b", "c"]] = []
    terms: Literal[True]
    avatar: Optional[Annotated[Upload, UploadField(max_size=500, accept="image/*")]] = None

signup = form(Signup)
done = wire("")

async def create(data: Signup):
    size = len(await data.avatar.read()) if data.avatar else 0
    done.value = f"{data.email}|{data.tags}|{size}"
    if data.name == "Go":
        navigate("/thanks")
---
<p id="done">{done}</p>
<form $bind={signup} @submit={create}>
  <input $bind={signup.email}>
  <p $if={signup.email.error}>ERR:{signup.email.error}</p>
  <input $bind={signup.name}>
  <input type="checkbox" value="a" $bind={signup.tags}>
  <input type="checkbox" value="b" $bind={signup.tags}>
  <input $bind={signup.terms}>
  <input $bind={signup.avatar}>
  <p $if={signup.avatar.error}>FILE:{signup.avatar.error}</p>
</form>
"""

VALID = {"email": "a@b.co", "name": "Al", "tags": ["a", "b"], "terms": "true"}
MODES = {
    "interactive": {},
    "non-interactive": {"interactive_server_mode": False},
    "stateless": {"stateless": True, "secret_key": SECRET},
}


@pytest.fixture(params=list(MODES))
def client(request):
    root = Path(tempfile.mkdtemp())
    pages = root / "pages"
    pages.mkdir()
    (pages / "index.wire").write_text(PAGE)
    (pages / "thanks.wire").write_text("<p>thanks</p>\n")
    app = PyWire(pages_dir=str(pages), max_upload_size=1024, **MODES[request.param])
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    shutil.rmtree(root, ignore_errors=True)


def _handler(client) -> str:
    html = client.get("/").text
    match = re.search(r'name="__pywire_handler" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def test_get_renders_a_multipart_form(client):
    html = client.get("/").text
    form = re.search(r"<form[^>]*>", html).group(0)
    assert 'method="post"' in form and 'enctype="multipart/form-data"' in form
    assert 'name="pywire-upload-token"' in html


def test_invalid_post_is_422_with_values_and_errors(client):
    handler = _handler(client)
    r = client.post(
        "/", data={"__pywire_handler": handler, "email": "bad", "name": "A", "x": "1"}
    )
    assert r.status_code == 422
    assert "ERR:Enter a valid email address" in r.text
    assert 'value="bad"' in r.text
    assert "core.min.js" in r.text  # a full page, not a fragment


def test_valid_post_runs_handler(client):
    handler = _handler(client)
    r = client.post("/", data={"__pywire_handler": handler, **VALID})
    assert r.status_code == 200
    assert (
        "a@b.co|[&#x27;a&#x27;, &#x27;b&#x27;]|0" in r.text
        or "a@b.co|['a', 'b']|0" in r.text
    )


def test_navigation_is_a_303(client):
    handler = _handler(client)
    r = client.post(
        "/",
        data={"__pywire_handler": handler, **VALID, "name": "Go"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == "/thanks"


def test_the_handler_itself_is_not_reachable(client):
    r = client.post("/", data={"__pywire_handler": "create", **VALID})
    assert r.status_code == 400
    assert "not a registered event handler" in r.text


def test_multipart_file_is_sized_from_bytes(client):
    handler = _handler(client)
    r = client.post(
        "/",
        data={"__pywire_handler": handler, **VALID},
        files={"avatar": ("a.png", b"x" * 100, "image/png")},
    )
    assert r.status_code == 200
    assert "|100</p>" in r.text


def test_upload_field_rules_render_and_apply(client):
    html = client.get("/").text
    avatar = re.search(r'<input[^>]*type="file"[^>]*>', html).group(0)
    assert 'accept="image/*"' in avatar and 'data-pw-max-size="500"' in avatar

    handler = _handler(client)
    r = client.post(
        "/",
        data={"__pywire_handler": handler, **VALID},
        files={"avatar": ("a.png", b"x" * 600, "image/png")},
    )
    assert r.status_code == 422
    assert "FILE:Choose a file no larger than 500 B" in r.text

    r = client.post(
        "/",
        data={"__pywire_handler": handler, **VALID},
        files={"avatar": ("a.txt", b"x", "text/plain")},
    )
    assert r.status_code == 422
    assert "FILE:Choose a file of type image/*" in r.text


def test_no_file_chosen_is_no_file(client):
    handler = _handler(client)
    r = client.post(
        "/",
        data={"__pywire_handler": handler, **VALID},
        files={"avatar": ("", b"", "application/octet-stream")},
    )
    assert r.status_code == 200
    assert "|0</p>" in r.text


def test_multipart_file_over_the_limit_is_413(client):
    handler = _handler(client)
    r = client.post(
        "/",
        data={"__pywire_handler": handler, **VALID},
        files={"avatar": ("a.png", b"x" * 2048, "image/png")},
    )
    assert r.status_code == 413


@pytest.mark.parametrize(
    "headers,status",
    [
        ({"origin": "https://evil.example"}, 403),
        ({"origin": "null"}, 403),
        ({"sec-fetch-site": "cross-site"}, 403),
        ({"sec-fetch-site": "same-site"}, 403),
        ({"sec-fetch-site": "same-origin", "origin": "https://evil.example"}, 422),
        ({"origin": "http://testserver"}, 422),
        ({}, 422),
    ],
)
def test_cross_site_posts_are_refused(client, headers, status):
    handler = _handler(client)
    r = client.post(
        "/", data={"__pywire_handler": handler, "email": "x"}, headers=headers
    )
    assert r.status_code == status


def test_stateless_event_carries_form_state_in_the_snapshot():
    root = Path(tempfile.mkdtemp())
    pages = root / "pages"
    pages.mkdir()
    (pages / "index.wire").write_text(PAGE)
    app = PyWire(pages_dir=str(pages), stateless=True, secret_key=SECRET)
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            html = c.get("/").text
            blob = html.split('_pywire_snapshot" type="text/plain">')[1].split(
                "</script>"
            )[0]

            def post(snapshot, form_data):
                r = c.post(
                    "/_pywire/stateless",
                    content=msgpack.packb(
                        {
                            "path": "/",
                            "handler": "_handler_0",
                            "data": {"type": "submit", "formData": form_data},
                            "snapshot": snapshot,
                        }
                    ),
                    headers={"Content-Type": "application/x-msgpack"},
                )
                assert r.status_code == 200
                return msgpack.unpackb(r.content, raw=False)

            out = post(blob, {"email": "bad", "name": "A"})
            assert "ERR:Enter a valid email address" in str(out["regions"])
            state = decode_snapshot(out["snapshot"], secret=SECRET.encode())["hooked"]
            assert state["signup"]["raw"]["email"] == ["bad"]
            assert state["signup"]["errors"]["email"][0]["code"] == "typeMismatch"

            # A later event restores the errors from the snapshot.
            out = post(out["snapshot"], {**VALID})
            assert "a@b.co" in str(out["regions"])
            assert "ERR:" not in str(out["regions"])
    finally:
        shutil.rmtree(root, ignore_errors=True)
