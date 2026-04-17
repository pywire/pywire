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
                    "<form method='post' @submit={handle_submit}>\n"
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
        response = self.client.post(
            "/form",
            data={"name": "World"},
            headers={"X-PyWire-Handler": "handle_submit"},
        )
        # Should get HTML response (not JSON, not error)
        assert response.status_code in (200, 303)
        content_type = response.headers.get("content-type", "")
        assert "text/html" in content_type or response.status_code == 303
        if response.status_code == 200:
            assert "Hello World" in response.text

    def test_form_post_without_submit_binding_returns_400(self):
        """POSTing without the X-PyWire-Handler header must fail loudly —
        the magic `handle_submit` fallback is gone."""
        response = self.client.post("/form", data={"name": "World"})
        assert response.status_code == 400


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


# ---------------------------------------------------------------------------
# Multi-form dispatch via @submit={handler_name}
# ---------------------------------------------------------------------------


class TestMultipleFormsPerPage:
    """Verify two forms on the same page route to distinct handlers via
    the ``X-PyWire-Handler`` header set by the PyWire client when a form
    bound via ``@submit={handler}`` is submitted."""

    def setup_method(self):
        self.app = _make_app(
            {
                "multi": (
                    "---\n"
                    "first_value = wire('')\n"
                    "second_value = wire('')\n"
                    "\n"
                    "async def handle_first(data):\n"
                    "    first_value.value = data.get('field', '').strip()\n"
                    "\n"
                    "async def handle_second(data):\n"
                    "    second_value.value = data.get('field', '').strip()\n"
                    "---\n"
                    "<p id='first'>First: {first_value}</p>\n"
                    "<p id='second'>Second: {second_value}</p>\n"
                    "<form method='post' @submit={handle_first}>\n"
                    "  <input name='field' />\n"
                    "  <button type='submit'>Send to first</button>\n"
                    "</form>\n"
                    "<form method='post' @submit={handle_second}>\n"
                    "  <input name='field' />\n"
                    "  <button type='submit'>Send to second</button>\n"
                    "</form>\n"
                ),
            },
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_initial_render_marks_handler_on_form(self):
        response = self.client.get("/multi")
        assert response.status_code == 200
        # The compiler annotates each form with data-on-submit so the
        # client can read the handler name and set the X-PyWire-Handler
        # header on submit.
        assert 'data-on-submit="handle_first"' in response.text
        assert 'data-on-submit="handle_second"' in response.text

    def test_post_to_first_only_updates_first(self):
        response = self.client.post(
            "/multi",
            data={"field": "alpha"},
            headers={"X-PyWire-Handler": "handle_first"},
        )
        assert response.status_code == 200
        assert "First: alpha" in response.text
        assert "Second: " in response.text
        assert "Second: alpha" not in response.text

    def test_post_to_second_only_updates_second(self):
        response = self.client.post(
            "/multi",
            data={"field": "beta"},
            headers={"X-PyWire-Handler": "handle_second"},
        )
        assert response.status_code == 200
        assert "Second: beta" in response.text
        assert "First: beta" not in response.text

    def test_post_to_missing_handler_returns_400(self):
        response = self.client.post(
            "/multi",
            data={"field": "x"},
            headers={"X-PyWire-Handler": "does_not_exist"},
        )
        assert response.status_code == 400
        assert "not found" in response.text


# ---------------------------------------------------------------------------
# <Form /> component with Pydantic validation in SSR
# ---------------------------------------------------------------------------


class TestFormComponentSSR:
    """Verify the built-in `<Form model=...>` component works in
    non-interactive mode — validation runs on the POSTed body, errors
    render inline, and `on_submit` only fires on valid data.
    """

    def setup_method(self):
        self.app = _make_app(
            {
                "signup": (
                    "---\n"
                    "from pydantic import BaseModel, Field\n"
                    "from pywire.components import Form\n"
                    "\n"
                    "class SignupModel(BaseModel):\n"
                    "    username: str = Field(min_length=3)\n"
                    "    age: int\n"
                    "\n"
                    "signup_form = ref()\n"
                    "success = wire('')\n"
                    "\n"
                    "async def handle_signup(user):\n"
                    "    success.value = f'Welcome {user.username}'\n"
                    "---\n"
                    "<p id='success'>{success}</p>\n"
                    "<Form model={SignupModel} @submit={handle_signup} $ref={signup_form}>\n"
                    "  <input name='username' />\n"
                    "  <small id='err-username'>{signup_form.errors.username.message}</small>\n"
                    "  <input name='age' />\n"
                    "  <small id='err-age'>{signup_form.errors.age.message}</small>\n"
                    "  <button type='submit'>Sign up</button>\n"
                    "</Form>\n"
                ),
            },
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_get_renders_form_with_component_scoped_handler(self):
        response = self.client.get("/signup")
        assert response.status_code == 200
        # Form component's internal `<form @submit={handle_submit}>` gets
        # prefixed at runtime with `_comp:{key}:` so the POST routes to
        # the component instance, not the page.
        assert 'data-on-submit="_comp:' in response.text

    def _extract_submit_value(self, html: str) -> str:
        import re

        match = re.search(r'data-on-submit="([^"]+)"', html)
        assert match is not None, "data-on-submit attribute not found"
        return match.group(1)

    def test_valid_data_invokes_on_submit(self):
        initial = self.client.get("/signup")
        submit_value = self._extract_submit_value(initial.text)

        response = self.client.post(
            "/signup",
            data={"username": "alice", "age": "30"},
            headers={"X-PyWire-Handler": submit_value},
        )
        assert response.status_code == 200
        assert "Welcome alice" in response.text

    def test_invalid_data_renders_errors_and_skips_on_submit(self):
        initial = self.client.get("/signup")
        submit_value = self._extract_submit_value(initial.text)

        response = self.client.post(
            "/signup",
            data={
                "username": "al",  # too short
                "age": "not-a-number",
            },
            headers={"X-PyWire-Handler": submit_value},
        )
        assert response.status_code == 200
        # on_submit should NOT have been called.
        assert "Welcome" not in response.text
        # Errors should appear inline for both fields.
        body = response.text
        assert "err-username" in body
        assert "err-age" in body


# ---------------------------------------------------------------------------
# E2E: Sync + async handler parity
# ---------------------------------------------------------------------------


class TestSyncAndAsyncHandlers:
    """`@submit={handler}` must work for both `def` and `async def` handlers
    without any extra user plumbing."""

    def setup_method(self):
        self.app = _make_app(
            {
                "sync": (
                    "---\n"
                    "seen = ''\n"
                    "\n"
                    "def handle_sync(data):\n"
                    "    global seen\n"
                    "    seen = data.get('name', '')\n"
                    "---\n"
                    "<p id='out'>seen={seen}</p>\n"
                    "<form method='post' @submit={handle_sync}>\n"
                    "  <input name='name' />\n"
                    "  <button type='submit'>Go</button>\n"
                    "</form>\n"
                ),
                "asyncp": (
                    "---\n"
                    "seen = ''\n"
                    "\n"
                    "async def handle_async(data):\n"
                    "    global seen\n"
                    "    seen = data.get('name', '')\n"
                    "---\n"
                    "<p id='out'>seen={seen}</p>\n"
                    "<form method='post' @submit={handle_async}>\n"
                    "  <input name='name' />\n"
                    "  <button type='submit'>Go</button>\n"
                    "</form>\n"
                ),
            },
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_sync_handler_runs(self):
        response = self.client.post(
            "/sync",
            data={"name": "alice"},
            headers={"X-PyWire-Handler": "handle_sync"},
        )
        assert response.status_code == 200
        assert "seen=alice" in response.text

    def test_async_handler_runs(self):
        response = self.client.post(
            "/asyncp",
            data={"name": "bob"},
            headers={"X-PyWire-Handler": "handle_async"},
        )
        assert response.status_code == 200
        assert "seen=bob" in response.text


# ---------------------------------------------------------------------------
# E2E: SPA form submit — fragment response
# ---------------------------------------------------------------------------


class TestSpaFormSubmit:
    """Form POSTs carrying `X-PyWire-Internal: form-submit` must return a
    body-only fragment so the client can morph it without replacing the
    whole document."""

    def setup_method(self):
        self.app = _make_app(
            {
                "spa": (
                    "---\n"
                    "seen = ''\n"
                    "\n"
                    "def handle(data):\n"
                    "    global seen\n"
                    "    seen = data.get('name', '')\n"
                    "---\n"
                    "<p id='out'>seen={seen}</p>\n"
                    "<form method='post' @submit={handle}>\n"
                    "  <input name='name' />\n"
                    "  <button type='submit'>Go</button>\n"
                    "</form>\n"
                ),
            },
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_standard_post_includes_client_scripts(self):
        """A plain POST with just the handler header still returns a full
        rehydratable page (no form-submit fragment header)."""
        response = self.client.post(
            "/spa",
            data={"name": "zed"},
            headers={"X-PyWire-Handler": "handle"},
        )
        assert response.status_code == 200
        assert "seen=zed" in response.text
        # init=True injects the meta/script tags.
        assert "_pywire_spa_meta" in response.text
        assert "pywire.core.min.js" in response.text

    def test_spa_post_omits_client_scripts(self):
        """With `X-PyWire-Internal: form-submit` the response is a morph
        fragment — scripts already loaded, don't re-inject."""
        response = self.client.post(
            "/spa",
            data={"name": "zed"},
            headers={
                "X-PyWire-Internal": "form-submit",
                "X-PyWire-Handler": "handle",
            },
        )
        assert response.status_code == 200
        assert "seen=zed" in response.text
        assert "_pywire_spa_meta" not in response.text
        assert "pywire.core.min.js" not in response.text
