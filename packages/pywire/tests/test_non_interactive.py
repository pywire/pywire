"""Tests for non-interactive server mode (interactive_server_mode=False).

Verifies: no WS routes, session-via-cookie, form POST handling,
capabilities endpoint, and event warnings.
"""

import shutil
import tempfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire
from pywire.runtime.session_middleware import (
    _sign_session_id,
    _verify_session_id,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(**kwargs) -> PyWire:
    """Create a minimal PyWire app."""
    test_dir = tempfile.mkdtemp()
    pages_dir = Path(test_dir) / "pages"
    pages_dir.mkdir()
    (pages_dir / "index.wire").write_text("<p>Home</p>")
    (pages_dir / "about.wire").write_text("<p>About</p>")
    app = PyWire(pages_dir=str(pages_dir), **kwargs)
    app._test_dir = test_dir
    return app


def _make_interactive_app(**kwargs) -> PyWire:
    return _make_app(interactive_server_mode=True, **kwargs)


def _make_non_interactive_app(**kwargs) -> PyWire:
    return _make_app(interactive_server_mode=False, **kwargs)


# ---------------------------------------------------------------------------
# Session signing tests
# ---------------------------------------------------------------------------


class TestSessionSigning:
    def test_sign_and_verify(self):
        secret = "test-secret-key"
        session_id = "abc123"
        signed = _sign_session_id(session_id, secret)
        assert "." in signed
        assert _verify_session_id(signed, secret) == session_id

    def test_verify_rejects_tampered(self):
        secret = "test-secret-key"
        signed = _sign_session_id("abc123", secret)
        # Tamper with the session ID
        tampered = "xyz789" + signed[signed.index(".") :]
        assert _verify_session_id(tampered, secret) is None

    def test_verify_rejects_no_dot(self):
        assert _verify_session_id("nosignature", "secret") is None

    def test_verify_rejects_wrong_secret(self):
        signed = _sign_session_id("abc123", "secret-a")
        assert _verify_session_id(signed, "secret-b") is None


class TestSessionSecretEnvWiring:
    """PYWIRE_SESSION_SECRET must flow through to the SessionMiddleware so
    sessions survive across workers / process restarts."""

    def test_shared_secret_accepts_cross_instance_cookie(self, monkeypatch):
        """Two apps started with the same PYWIRE_SESSION_SECRET should
        validate each other's session cookies — multi-worker deploy."""
        monkeypatch.setenv("PYWIRE_SESSION_SECRET", "shared-deploy-secret")
        app_a = _make_non_interactive_app()
        app_b = _make_non_interactive_app()
        try:
            client_a = TestClient(app_a, raise_server_exceptions=False)
            # Issue a cookie from worker A.
            res_a = client_a.get("/")
            assert res_a.status_code == 200
            cookie = res_a.cookies.get("pywire_session")
            assert cookie is not None

            # Hand-carry it to worker B. If the secret were not shared, the
            # middleware would reject the signature and re-issue a new cookie.
            client_b = TestClient(app_b, raise_server_exceptions=False)
            res_b = client_b.get("/", cookies={"pywire_session": cookie})
            # B must NOT issue a new cookie — it recognized A's signature.
            assert "pywire_session" not in res_b.cookies
        finally:
            shutil.rmtree(app_a._test_dir, ignore_errors=True)
            shutil.rmtree(app_b._test_dir, ignore_errors=True)

    def test_random_secret_rejects_cross_instance_cookie(self, monkeypatch):
        """Without PYWIRE_SESSION_SECRET each app gets its own random key —
        A's cookie is invalid on B. This is the documented failure mode we
        warn about."""
        monkeypatch.delenv("PYWIRE_SESSION_SECRET", raising=False)
        monkeypatch.delenv("PYWIRE_DEV_MODE", raising=False)
        app_a = _make_non_interactive_app()
        app_b = _make_non_interactive_app()
        try:
            client_a = TestClient(app_a, raise_server_exceptions=False)
            res_a = client_a.get("/")
            cookie = res_a.cookies.get("pywire_session")
            assert cookie is not None

            client_b = TestClient(app_b, raise_server_exceptions=False)
            res_b = client_b.get("/", cookies={"pywire_session": cookie})
            # B rejects A's signature → re-issues its own cookie.
            assert res_b.cookies.get("pywire_session") is not None
            assert res_b.cookies.get("pywire_session") != cookie
        finally:
            shutil.rmtree(app_a._test_dir, ignore_errors=True)
            shutil.rmtree(app_b._test_dir, ignore_errors=True)

    def test_dev_mode_persists_secret_across_restarts(self, monkeypatch):
        """`pywire dev` sets PYWIRE_DEV_MODE=1. The dev signing key is
        derived deterministically from machine identity + pages_dir (no
        secret written to disk — CodeQL flagged the prior file cache), so
        sessions survive restarts and a second launch against the same
        pages_dir validates cookies from the first.
        """
        monkeypatch.delenv("PYWIRE_SESSION_SECRET", raising=False)
        monkeypatch.setenv("PYWIRE_DEV_MODE", "1")

        app_a = _make_non_interactive_app()

        client_a = TestClient(app_a, raise_server_exceptions=False)
        res_a = client_a.get("/")
        cookie = res_a.cookies.get("pywire_session")
        assert cookie is not None

        # Second instance, same pages_dir — deterministic derivation means
        # the signing secret matches, so cookies from the first instance
        # validate without any file-backed cache.
        app_b = PyWire(pages_dir=str(app_a.pages_dir))
        app_b._test_dir = app_a._test_dir  # piggyback for teardown parity
        try:
            client_b = TestClient(app_b, raise_server_exceptions=False)
            res_b = client_b.get("/", cookies={"pywire_session": cookie})
            # Same secret → signature accepted → no new cookie issued.
            assert "pywire_session" not in res_b.cookies
        finally:
            shutil.rmtree(app_a._test_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Non-interactive mode: route gating
# ---------------------------------------------------------------------------


class TestNonInteractiveRouteGating:
    def setup_method(self):
        self.app = _make_non_interactive_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_no_websocket_route(self):
        """WebSocket endpoint should not be registered."""
        # Attempting a WebSocket upgrade should fail (404 or connection refused)
        with pytest.raises(Exception):
            with self.client.websocket_connect("/_pywire/ws"):
                pass

    def test_capabilities_shows_http_only(self):
        """Capabilities endpoint should report http-only transport."""
        response = self.client.get("/_pywire/capabilities")
        assert response.status_code == 200
        data = response.json()
        assert data["interactive"] is False
        assert "http-only" in data["transports"]

    def test_pages_still_render(self):
        """Pages should still render via HTTP GET."""
        response = self.client.get("/")
        assert response.status_code == 200
        assert "Home" in response.text

    def test_about_page_renders(self):
        response = self.client.get("/about")
        assert response.status_code == 200
        assert "About" in response.text


class TestInteractiveModeCapabilities:
    def setup_method(self):
        self.app = _make_interactive_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_capabilities_shows_interactive(self):
        response = self.client.get("/_pywire/capabilities")
        data = response.json()
        assert data["interactive"] is True
        assert "websocket" in data["transports"]


# ---------------------------------------------------------------------------
# Non-interactive mode: session cookie
# ---------------------------------------------------------------------------


class TestNonInteractiveSessionCookie:
    def setup_method(self):
        self.app = _make_non_interactive_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_first_request_sets_session_cookie(self):
        """First request should get a pywire_session cookie."""
        response = self.client.get("/")
        assert response.status_code == 200
        cookies = response.cookies
        # The session cookie should be set
        assert "pywire_session" in response.headers.get("set-cookie", "")

    def test_session_persists_across_requests(self):
        """Session cookie should be accepted on subsequent requests."""
        # First request — get cookie
        response1 = self.client.get("/")
        assert response1.status_code == 200

        # Second request — cookie should be sent back
        response2 = self.client.get("/about")
        assert response2.status_code == 200


# ---------------------------------------------------------------------------
# Non-interactive mode: form POST
# ---------------------------------------------------------------------------


class TestNonInteractiveFormPost:
    def setup_method(self):
        test_dir = tempfile.mkdtemp()
        pages_dir = Path(test_dir) / "pages"
        pages_dir.mkdir()
        # Simple page with a form
        (pages_dir / "counter.wire").write_text(
            "---\n"
            "async def handle_submit(data):\n"
            "    pass\n"
            "---\n"
            "<p>Counter Page</p>\n"
            "<form method='post' @submit={handle_submit}>"
            "<button type='submit'>Submit</button></form>"
        )
        self.app = PyWire(
            pages_dir=str(pages_dir),
            interactive_server_mode=False,
        )
        self.app._test_dir = test_dir
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_form_post_returns_html(self):
        """Form POST should return rendered HTML, not JSON."""
        response = self.client.post(
            "/counter",
            data={"action": "increment"},
            headers={"X-PyWire-Handler": "handle_submit"},
        )
        assert response.status_code == 200
        assert response.headers.get("content-type", "").startswith("text/html")

    def test_form_post_missing_submit_binding_returns_400(self):
        """POST without handler signal (no header, no hidden field) must
        surface a loud 400 so users notice the missing
        `@submit={handler}` binding."""
        response = self.client.post("/counter", data={"action": "increment"})
        assert response.status_code == 400
        assert "X-PyWire-Handler" in response.text


# ---------------------------------------------------------------------------
# Non-interactive mode: SPA metadata
# ---------------------------------------------------------------------------


class TestNonInteractiveSPAMetadata:
    def setup_method(self):
        self.app = _make_non_interactive_app(enable_pjax=True)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_spa_metadata_includes_interactive_flag(self):
        """SPA metadata should include interactive=false."""
        response = self.client.get("/")
        assert response.status_code == 200
        # Check that the SPA metadata script tag is present
        assert "_pywire_spa_meta" in response.text
        # Check interactive flag
        assert '"interactive": false' in response.text
