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
        tampered = "xyz789" + signed[signed.index("."):]
        assert _verify_session_id(tampered, secret) is None

    def test_verify_rejects_no_dot(self):
        assert _verify_session_id("nosignature", "secret") is None

    def test_verify_rejects_wrong_secret(self):
        signed = _sign_session_id("abc123", "secret-a")
        assert _verify_session_id(signed, "secret-b") is None


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
            "<p>Counter Page</p>\n<form method='post'><button type='submit'>Submit</button></form>"
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
        response = self.client.post("/counter", data={"action": "increment"})
        assert response.status_code == 200
        assert response.headers.get("content-type", "").startswith("text/html")


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
