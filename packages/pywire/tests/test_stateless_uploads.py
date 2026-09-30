"""Stateless mode: file uploads are plain HTTP and must work without WS (T27).

Uploads are not an interactive transport feature: the browser POSTs the
file to ``/_pywire/upload`` with the page-issued token, then the submit
carries the returned upload id and the handler gets an ``Upload``. Both
halves must work in a ``stateless=True`` app.
"""

import asyncio
from pathlib import Path

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire
from pywire.storage import MemoryStore

FIXTURE_PAGES = Path(__file__).parent / "fixtures" / "stateless_app" / "pages"
SECRET = "test-secret-key-at-least-32-bytes"

_MSGPACK = {"Content-Type": "application/x-msgpack"}


@pytest.fixture()
def client():
    app = PyWire(pages_dir=str(FIXTURE_PAGES), stateless=True, secret_key=SECRET)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _token(html: str) -> str:
    return html.split('name="pywire-upload-token" content="')[1].split('"')[0]


def _blob(html: str) -> str:
    return html.split('_pywire_snapshot" type="text/plain">')[1].split("</script>")[0]


def test_one_client_can_only_stage_so_much(client):
    app = client.app
    app.max_upload_size = 100
    app.upload_budget_files = 2  # 200 bytes an hour per client
    token = _token(client.get("/upload").text)

    def upload(size: int):
        return client.post(
            "/_pywire/upload",
            files={"doc": ("a.txt", b"x" * size, "text/plain")},
            headers={"X-Upload-Token": token},
        )

    assert upload(90).status_code == 200
    assert upload(90).status_code == 200
    # A fresh token from another page view doesn't reset the budget.
    token = _token(client.get("/upload").text)
    assert upload(90).status_code == 429


def test_upload_route_mounted_in_stateless_mode(client):
    paths = {getattr(r, "path", None) for r in client.app.app.routes}
    assert "/_pywire/upload" in paths


def test_upload_reaches_handler(client):
    r = client.get("/upload")
    assert r.status_code == 200
    token = _token(r.text)

    up = client.post(
        "/_pywire/upload",
        files={"doc": ("hello.txt", b"hello world", "text/plain")},
        headers={"X-Upload-Token": token},
    )
    assert up.status_code == 200
    (upload_id,) = up.json()["doc"]

    # The submit carries the id; the stateless handler gets the file.
    r = client.post(
        "/_pywire/stateless",
        content=msgpack.packb(
            {
                "path": "/upload",
                "handler": "save",
                "data": {
                    "type": "submit",
                    "formData": {
                        "doc": {"_upload_id": upload_id, "_upload_token": token}
                    },
                },
                "snapshot": _blob(r.text),
            }
        ),
        headers=_MSGPACK,
    )
    assert r.status_code == 200
    msg = msgpack.unpackb(r.content, raw=False)
    assert any("hello.txt:hello world" in reg["html"] for reg in msg.get("regions", []))


def _submit(client, html, ref):
    return client.post(
        "/_pywire/stateless",
        content=msgpack.packb(
            {
                "path": "/upload",
                "handler": "save",
                "data": {"type": "submit", "formData": {"doc": ref}},
                "snapshot": _blob(html),
            }
        ),
        headers=_MSGPACK,
    )


def test_an_upload_id_only_resolves_with_the_token_it_was_sent_with(client):
    page = client.get("/upload").text
    token = _token(page)
    up = client.post(
        "/_pywire/upload",
        files={"doc": ("secret.txt", b"mine", "text/plain")},
        headers={"X-Upload-Token": token},
    )
    (upload_id,) = up.json()["doc"]

    # Another browser has its own page, and its own token.
    other = client.get("/upload").text
    for ref in (
        {"_upload_id": upload_id},
        {"_upload_id": upload_id, "_upload_token": _token(other)},
    ):
        r = _submit(client, other, ref)
        assert b"secret.txt:mine" not in r.content


def _staged(app) -> int:
    async def count() -> int:
        return len([k async for k in app.uploads.store.list("")])

    return asyncio.run(count())


def test_upload_limits_count_the_body_as_it_arrives():
    app = PyWire(
        pages_dir=str(FIXTURE_PAGES),
        stateless=True,
        secret_key=SECRET,
        max_upload_size=1000,
        upload_store=MemoryStore(),
    )
    with TestClient(app, raise_server_exceptions=False) as c:
        token = _token(c.get("/upload").text)
        headers = {"X-Upload-Token": token}

        # Several files each under the limit: fine, even though together
        # they are over it.
        up = c.post(
            "/_pywire/upload",
            files=[("doc", (f"{i}.txt", b"x" * 600, "text/plain")) for i in range(3)],
            headers=headers,
        )
        assert up.status_code == 200 and len(up.json()["doc"]) == 3

        # One file over the limit is refused, and nothing it sent is kept.
        before = _staged(app)
        up = c.post(
            "/_pywire/upload",
            files=[
                ("doc", ("ok.txt", b"x" * 10, "text/plain")),
                ("doc", ("big.txt", b"x" * 1001, "text/plain")),
            ],
            headers=headers,
        )
        assert up.status_code == 413
        assert _staged(app) == before

        # Too many files: a 400, not a 500.
        up = c.post(
            "/_pywire/upload",
            files=[("doc", (f"{i}.txt", b"x", "text/plain")) for i in range(11)],
            headers=headers,
        )
        assert up.status_code == 400

        # A chunked body declares no length; it is counted as it arrives.
        def chunks():
            yield b"--b\r\nContent-Disposition: form-data; name=doc; filename=a\r\n\r\n"
            for _ in range(200):
                yield b"x" * 65536

        up = c.post(
            "/_pywire/upload",
            content=chunks(),
            headers={**headers, "content-type": "multipart/form-data; boundary=b"},
        )
        assert up.status_code == 413


def test_traversal_upload_token_cannot_delete_outside_dir(client):
    """X-Upload-Token path traversal must not delete ``*.json`` outside the
    token dir (``_token_file_path`` joined the raw header value)."""
    import json
    import os

    app = client.app
    probe_name = f"pywire_traversal_probe_{os.getpid()}"
    target = (app._upload_token_dir / ".." / ".." / f"{probe_name}.json").resolve()
    target.write_text(json.dumps({"session_id": None, "issued_ts": 0.0}))
    try:
        up = client.post(
            "/_pywire/upload",
            files={"doc": ("x.txt", b"x", "text/plain")},
            headers={"X-Upload-Token": f"../../{probe_name}"},
        )
        assert up.status_code == 403
        assert target.exists(), "traversal token deleted a file outside the token dir"
    finally:
        target.unlink(missing_ok=True)


def test_a_page_view_stores_no_upload_token(client):
    app = client.app
    before = set(app._upload_token_dir.iterdir())
    tokens = {_token(client.get("/upload").text) for _ in range(20)}
    assert len(tokens) == 20
    assert set(app._upload_token_dir.iterdir()) == before


def test_upload_tokens_are_checked(client):
    token = _token(client.get("/upload").text)
    stamp, nonce, mac = token.split("_")

    def post(t):
        return client.post(
            "/_pywire/upload",
            files={"doc": ("a.txt", b"a", "text/plain")},
            headers={"X-Upload-Token": t},
        ).status_code

    assert post(f"{stamp}_{nonce}_{'0' * len(mac)}") == 403
    assert post(f"{int(stamp, 16) + 1:x}_{nonce}_{mac}") == 403
    old = client.app._issue_upload_token()
    old_stamp, rest = old.split("_", 1)
    body = f"{int(old_stamp, 16) - 3600:x}_{rest.split('_')[0]}"
    import hashlib
    import hmac

    expired = hmac.new(client.app._upload_key(), body.encode(), hashlib.sha256)
    assert post(f"{body}_{expired.hexdigest()}") == 403
    assert post(token) == 200


PLAIN_PAGE = """---
out = wire('')

async def save(event):
    out.value = "/".join(type(event.get(k)).__name__ for k in ("doc", "note"))
---
<p id="out">{out}</p>
<form @submit={save}>
  <input type="file" name="doc" />
  <input name="note" />
</form>
"""


def test_a_plain_handler_gets_files_only_under_its_file_inputs(tmp_path):
    (tmp_path / "plain.wire").write_text(PLAIN_PAGE)
    app = PyWire(pages_dir=str(tmp_path), stateless=True, secret_key=SECRET)
    with TestClient(app, raise_server_exceptions=False) as c:
        page = c.get("/plain").text
        token = _token(page)
        up = c.post(
            "/_pywire/upload",
            files=[
                ("doc", ("a.txt", b"a", "text/plain")),
                ("doc", ("b.txt", b"b", "text/plain")),
            ],
            headers={"X-Upload-Token": token},
        )
        first, second = up.json()["doc"]
        r = c.post(
            "/_pywire/stateless",
            content=msgpack.packb(
                {
                    "path": "/plain",
                    "handler": "save",
                    "data": {
                        "type": "submit",
                        "formData": {
                            "doc": {"_upload_id": first, "_upload_token": token},
                            "note": {"_upload_id": second, "_upload_token": token},
                        },
                    },
                    "snapshot": _blob(page),
                }
            ),
            headers=_MSGPACK,
        )
        assert r.status_code == 200
        html = "".join(
            reg["html"] for reg in msgpack.unpackb(r.content, raw=False)["regions"]
        )
        assert "Upload/NoneType" in html
