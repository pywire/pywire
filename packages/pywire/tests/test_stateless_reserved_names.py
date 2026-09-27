"""Stateless tier: request-bound names like ``query`` can't be page state (#333)."""

import base64
import hashlib
import hmac

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.compiler.exceptions import PyWireSyntaxError
from pywire.runtime.app import PyWire
from pywire.runtime.loader import PageLoader

SECRET = "test-secret-key"
_MSGPACK = {"Content-Type": "application/x-msgpack"}

READS_QUERY = """---
seen = wire("")

def look():
    seen.value = "q=" + query.get("q", "none")
---
<p id="seen">{seen}</p>
<button @click={look()}>look</button>
"""


def _client(tmp_path, source: str) -> TestClient:
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.wire").write_text(source)
    app = PyWire(pages_dir=str(pages), stateless=True, secret_key=SECRET)
    return TestClient(app, raise_server_exceptions=False)


def _sign(snapshot: dict) -> str:
    raw = msgpack.packb(snapshot)
    sig = hmac.new(SECRET.encode(), raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig + raw).decode("ascii")


@pytest.mark.parametrize("name", ["query", "params", "request"])
def test_reserved_page_variable_fails_to_compile(tmp_path, name: str) -> None:
    source = f'---\n{name} = wire("")\n---\n<p>{{{name}}}</p>\n'
    with _client(tmp_path, source) as client:
        response = client.get("/")

    assert response.status_code == 500
    assert "_pywire_snapshot" not in response.text
    with pytest.raises(PyWireSyntaxError, match=f"'{name}' is a reserved"):
        PageLoader().load(tmp_path / "pages" / "index.wire")


def test_signed_snapshot_cannot_overwrite_request_query(tmp_path) -> None:
    with _client(tmp_path, READS_QUERY) as client:
        page = client.get("/?q=real")
        blob = page.text.split('_pywire_snapshot" type="text/plain">')[1]
        snapshot = {
            "attrs": {"seen": "", "query": {"q": "forged"}, "_region_cache": {}},
            "wire_tags": {"seen": "primitive"},
            "page_class": "IndexPage",
        }
        forged = _sign(snapshot)
        assert forged != blob.split("</script>")[0]

        response = client.post(
            "/_pywire/stateless",
            content=msgpack.packb(
                {
                    "path": "/?q=real",
                    "handler": "_handler_0",
                    "data": {},
                    "snapshot": forged,
                }
            ),
            headers=_MSGPACK,
        )

    assert response.status_code == 200, response.content
    body = msgpack.unpackb(response.content, raw=False)
    html = "".join(r.get("html", "") for r in body["regions"])
    assert "q=real" in html
    assert "forged" not in html
