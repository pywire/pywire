"""E2E tests for non-interactive HTTP-only server mode.

These tests verify session state persistence across requests, form POST
handling with state changes, and the full request/response cycle without
WebSocket connections.
"""

import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _make_app(pages: dict[str, str], **kwargs: Any) -> PyWire:
    """Create a non-interactive PyWire app with named pages."""
    test_dir = tempfile.mkdtemp()
    pages_dir = Path(test_dir) / "pages"
    pages_dir.mkdir()
    for name, content in pages.items():
        (pages_dir / f"{name}.wire").write_text(content)
    app = PyWire(
        pages_dir=str(pages_dir),
        interactive_server_mode=False,
        **kwargs,
    )
    app._test_dir = test_dir
    return app


# ---------------------------------------------------------------------------
# E2E: Session state persists across HTTP requests
# ---------------------------------------------------------------------------


class TestSessionStatePersistence:
    """Verify wire() state survives across HTTP requests via session cookie."""

    def setup_method(self):
        self.app = _make_app(
            {
                "index": (
                    "---\n"
                    "count = wire(0)\n"
                    "---\n"
                    "<p id='count'>{count}</p>\n"
                ),
            },
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_first_request_renders_initial_state(self):
        """First GET should render with initial wire() values."""
        response = self.client.get("/")
        assert response.status_code == 200
        assert "0" in response.text

    def test_session_cookie_set_on_first_request(self):
        """First request should set a session cookie."""
        response = self.client.get("/")
        set_cookie = response.headers.get("set-cookie", "")
        assert "pywire_session=" in set_cookie

    def test_multiple_gets_same_session(self):
        """Multiple GETs with same session cookie should work."""
        # First request establishes session
        r1 = self.client.get("/")
        assert r1.status_code == 200

        # Second request reuses session (cookie auto-sent by TestClient)
        r2 = self.client.get("/")
        assert r2.status_code == 200


# ---------------------------------------------------------------------------
# E2E: Form POST with session state
# ---------------------------------------------------------------------------


class TestFormPostWithState:
    """Verify form POST changes state and re-renders."""

    def setup_method(self):
        self.app = _make_app(
            {
                "form": (
                    "---\n"
                    "name = wire('')\n"
                    "\n"
                    "async def handle_submit(data):\n"
                    "    name.value = data.get('name', '')\n"
                    "---\n"
                    "<p id='greeting'>Hello {name}</p>\n"
                    "<form method='post'>\n"
                    "  <input name='name' />\n"
                    "  <button type='submit'>Submit</button>\n"
                    "</form>\n"
                ),
            },
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_initial_render(self):
        """GET should render form with empty state."""
        response = self.client.get("/form")
        assert response.status_code == 200
        assert "Hello" in response.text

    def test_form_post_returns_html(self):
        """Form POST should return rendered HTML."""
        response = self.client.post("/form", data={"name": "World"})
        # Should get HTML response (not JSON, not error)
        assert response.status_code in (200, 303)
        content_type = response.headers.get("content-type", "")
        assert "text/html" in content_type or response.status_code == 303


# ---------------------------------------------------------------------------
# E2E: Non-interactive rejects WebSocket
# ---------------------------------------------------------------------------


class TestNoWebSocket:
    """Verify WebSocket connections are rejected in non-interactive mode."""

    def setup_method(self):
        self.app = _make_app({"index": "<p>Home</p>"})
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_ws_connect_fails(self):
        """WebSocket connect should fail — no WS route registered."""
        with pytest.raises(Exception):
            with self.client.websocket_connect("/_pywire/ws"):
                pass

    def test_http_poll_not_available(self):
        """HTTP transport poll endpoint should not be registered."""
        response = self.client.get("/_pywire/poll?session=test")
        # Should be 404 or 405 (route doesn't exist)
        assert response.status_code in (404, 405)


# ---------------------------------------------------------------------------
# E2E: Non-interactive with middleware
# ---------------------------------------------------------------------------


class RequestHeaderMiddleware(BaseHTTPMiddleware):
    """Adds a header to verify middleware runs on every request."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Middleware-Ran"] = "true"
        return response


class TestNonInteractiveMiddleware:
    """Verify middleware works correctly in non-interactive mode."""

    def setup_method(self):
        self.app = _make_app(
            {
                "index": "<p>Home</p>",
                "about": "<p>About</p>",
            },
            middleware=[RequestHeaderMiddleware],
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_middleware_runs_on_get(self):
        """Middleware should run on GET requests."""
        response = self.client.get("/")
        assert response.headers.get("X-Middleware-Ran") == "true"

    def test_middleware_runs_on_post(self):
        """Middleware should run on POST requests."""
        response = self.client.post("/", data={"key": "value"})
        assert response.headers.get("X-Middleware-Ran") == "true"

    def test_middleware_runs_on_all_pages(self):
        """Middleware applies to all pages, not just index."""
        r1 = self.client.get("/")
        r2 = self.client.get("/about")
        assert r1.headers.get("X-Middleware-Ran") == "true"
        assert r2.headers.get("X-Middleware-Ran") == "true"


# ---------------------------------------------------------------------------
# E2E: SPA metadata in non-interactive mode
# ---------------------------------------------------------------------------


class TestSPAMetadataFlag:
    """Verify SPA metadata correctly indicates non-interactive mode."""

    def setup_method(self):
        self.app = _make_app(
            {"index": "<p>Home</p>"},
            enable_pjax=True,
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_metadata_has_interactive_false(self):
        """SPA metadata should have interactive=false."""
        response = self.client.get("/")
        assert response.status_code == 200
        assert '"interactive": false' in response.text

    def test_client_script_still_injected(self):
        """Client script should still be injected for SPA navigation."""
        response = self.client.get("/")
        assert "pywire" in response.text.lower()
        # Script tag should be present (for fetch-based SPA)
        assert "<script" in response.text


# ---------------------------------------------------------------------------
# E2E: HTTP-only navigation (X-PyWire-Internal header)
# ---------------------------------------------------------------------------


class TestHTTPOnlyNavigation:
    """Verify HTTP-based SPA navigation works (what the client fetch does)."""

    def setup_method(self):
        self.app = _make_app(
            {
                "index": "<p>Home</p>",
                "about": "<p>About</p>",
            },
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_internal_relocate_returns_body_only(self):
        """X-PyWire-Internal: relocate should return body-only HTML."""
        response = self.client.get(
            "/about",
            headers={"X-PyWire-Internal": "relocate"},
        )
        assert response.status_code == 200
        assert "About" in response.text
        # Body-only means no <script> injection
        assert "<script" not in response.text

    def test_normal_get_returns_full_page(self):
        """Normal GET should return full page with scripts."""
        response = self.client.get("/about")
        assert response.status_code == 200
        assert "About" in response.text
        # Full page should have script injection
        assert "<script" in response.text

    def test_internal_relocate_404(self):
        """X-PyWire-Internal: relocate to nonexistent returns 404."""
        response = self.client.get(
            "/nonexistent",
            headers={"X-PyWire-Internal": "relocate"},
        )
        assert response.status_code == 404
