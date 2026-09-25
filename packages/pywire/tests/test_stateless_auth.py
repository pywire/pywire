"""{$auth} on the stateless tier resolves within the same request.

One-shot responses have no push channel, so ``{$auth}`` must carry the
final ``allowed``/``denied`` view in the response that also contains the
region. Auth verdicts are NEVER serialized into snapshots: every stateless
request re-evaluates, so permission revocation is visible on the very next
request (security invariant — pinned here).
"""

import shutil
import tempfile
from pathlib import Path

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.auth import Claim, ClaimsPrincipal
from pywire.runtime.app import PyWire
from pywire.runtime.snapshot_codec import decode_snapshot

SECRET = "test-secret-key"

# $then form: the authorizing body is distinct from the resolved body so the
# payload proves WHICH view shipped. ``{ok}`` renders True/False.
AUTH_PAGE = (
    "---\n"
    "count = wire(0)\n"
    "\n"
    "def increment(data):\n"
    "    count.value += 1\n"
    "---\n"
    "<p>{$auth claims=[(\"role\", \"admin\")]}"
    "PENDING-VIEW{$then ok}RESOLVED-{ok}{/auth}</p>\n"
    "<form method='post' @submit={increment}>\n"
    "  <button>go</button>\n"
    "</form>\n"
)

ADMIN = ClaimsPrincipal(
    is_authenticated=True,
    name="test",
    user_id="x:1",
    claims=[Claim(type="role", value="admin")],
)

# Mutable principal holder: revocation tests flip this between requests,
# exactly like a real session whose roles changed server-side.
_PRINCIPAL = {"value": ADMIN}


class _AuthApp(PyWire):
    def get_user(self, request):
        return _PRINCIPAL["value"]


def _make_client(principal):
    _PRINCIPAL["value"] = principal
    test_dir = tempfile.mkdtemp()
    pages_dir = Path(test_dir) / "pages"
    pages_dir.mkdir()
    (pages_dir / "authy.wire").write_text(AUTH_PAGE)
    app = _AuthApp(
        pages_dir=str(pages_dir),
        stateless=True,
        secret_key=SECRET,
        interactive_server_mode=False,
    )
    return TestClient(app, raise_server_exceptions=False), test_dir


def _blob(html: str) -> str:
    return html.split('_pywire_snapshot" type="text/plain">')[1].split("</script>")[0]


def _payload_text(msg: dict) -> str:
    return msg.get("html", "") + " ".join(
        reg.get("html", "") for reg in msg.get("regions", [])
    )


def _stateless_post(client, blob: str, handler: str = ""):
    return client.post(
        "/_pywire/stateless",
        content=msgpack.packb(
            {"path": "/authy", "handler": handler, "data": {}, "snapshot": blob}
        ),
        headers={"Content-Type": "application/x-msgpack"},
    )


def test_stateless_load_resolves_auth_allowed():
    """Page load carries the resolved (allowed) view — not PENDING."""
    client, td = _make_client(ADMIN)
    try:
        html = client.get("/authy").text
        assert "RESOLVED-True" in html
        assert "PENDING-VIEW" not in html
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_stateless_load_resolves_auth_denied():
    """Page load carries the resolved (denied) view — not PENDING."""
    client, td = _make_client(None)
    try:
        html = client.get("/authy").text
        assert "RESOLVED-False" in html
        assert "PENDING-VIEW" not in html
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_auth_verdict_never_enters_snapshot():
    """Security invariant: snapshots carry no auth verdict state.

    If a verdict were ever serialized, a client could replay a snapshot
    minted under an allowed principal after revocation.
    """
    client, td = _make_client(ADMIN)
    try:
        html = client.get("/authy").text
        snap = decode_snapshot(_blob(html), secret=SECRET.encode())
        assert not any("auth" in key for key in snap), snap.keys()
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_revocation_takes_effect_on_next_stateless_request():
    """A snapshot minted under an allowed principal must not cache the
    verdict: after revocation the very next request sees ``denied``."""
    client, td = _make_client(ADMIN)
    try:
        html = client.get("/authy").text
        assert "RESOLVED-True" in html  # minted while allowed
        blob = _blob(html)

        _PRINCIPAL["value"] = None  # revoked
        r = _stateless_post(client, blob)
        assert r.status_code == 200
        body = _payload_text(msgpack.unpackb(r.content, raw=False))
        assert "RESOLVED-False" in body, "cached verdict survived revocation"
        assert "RESOLVED-True" not in body
    finally:
        _PRINCIPAL["value"] = ADMIN
        shutil.rmtree(td, ignore_errors=True)


def test_no_js_form_re_render_carries_resolved_auth():
    """The no-JS form path (``__pywire_handler`` hidden input) re-renders
    with the resolved view."""
    client, td = _make_client(ADMIN)
    try:
        r = client.post("/authy", data={"__pywire_handler": "increment", "x": "1"})
        assert r.status_code == 200
        assert "RESOLVED-True" in r.text
        assert "PENDING-VIEW" not in r.text
    finally:
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
