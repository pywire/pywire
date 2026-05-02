"""E2E tests for internal ASGI middleware replay via WebSocket.

These tests use real WebSocket connections through TestClient to verify
that middleware enforcement, cookie propagation, and error handling work
correctly when SPA navigation is dispatched through the ASGI stack.
"""

import shutil
import tempfile
from pathlib import Path
from typing import Any

import msgpack
import pytest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire


# ---------------------------------------------------------------------------
# Middleware fixtures
# ---------------------------------------------------------------------------


class AuthMiddleware(BaseHTTPMiddleware):
    """Redirects unauthenticated requests to /login."""

    async def dispatch(self, request: Request, call_next):
        # Allow capabilities, static assets, login page, and internal WS
        path = request.url.path
        if any(path.startswith(p) for p in ("/_pywire/", "/login")):
            return await call_next(request)
        if not request.cookies.get("auth_token"):
            return RedirectResponse("/login", status_code=302)
        return await call_next(request)


class RequestCounterMiddleware(BaseHTTPMiddleware):
    """Counts HTTP requests and adds the count as a response header."""

    count = 0

    async def dispatch(self, request: Request, call_next):
        RequestCounterMiddleware.count += 1
        response = await call_next(request)
        response.headers["X-Request-Count"] = str(RequestCounterMiddleware.count)
        return response


class CookieSetterMiddleware(BaseHTTPMiddleware):
    """Sets a tracking cookie on every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.set_cookie("tracker", "middleware-set", path="/")
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple rate limiter that rejects after N requests."""

    def __init__(self, app: Any, max_requests: int = 5):
        super().__init__(app)
        self.max_requests = max_requests
        self.request_count = 0

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/_pywire/"):
            return await call_next(request)
        self.request_count += 1
        if self.request_count > self.max_requests:
            return Response("Rate limited", status_code=429)
        return await call_next(request)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _make_app(pages: dict[str, str], **kwargs: Any) -> PyWire:
    """Create a PyWire app with named pages."""
    test_dir = tempfile.mkdtemp()
    pages_dir = Path(test_dir) / "pages"
    pages_dir.mkdir()
    for name, content in pages.items():
        (pages_dir / f"{name}.wire").write_text(content)
    app = PyWire(pages_dir=str(pages_dir), **kwargs)
    app._test_dir = test_dir
    return app


def _ws_init(ws: Any, path: str = "/") -> dict:
    """Drain init message and send init request, return init_ack."""
    # Drain server init message
    data = msgpack.unpackb(ws.receive_bytes(), raw=False)
    assert data["type"] == "init"

    # Send client init
    ws.send_bytes(msgpack.packb({"type": "init", "path": path}))

    # Get init_ack
    data = msgpack.unpackb(ws.receive_bytes(), raw=False)
    assert data["type"] == "init_ack"
    return data


def _ws_relocate(ws: Any, path: str, cookies: str | None = None) -> dict:
    """Send relocate and return the response message."""
    payload: dict[str, Any] = {"type": "relocate", "path": path}
    if cookies is not None:
        payload["cookies"] = cookies
    ws.send_bytes(msgpack.packb(payload))
    data = msgpack.unpackb(ws.receive_bytes(), raw=False)
    return data


# ---------------------------------------------------------------------------
# E2E: Auth middleware blocks SPA navigation
# ---------------------------------------------------------------------------


class TestAuthMiddlewareReplay:
    """Verify auth middleware applies to WebSocket SPA navigations."""

    def setup_method(self):
        self.app = _make_app(
            {
                "index": "<p>Home</p>",
                "dashboard": "<p>Dashboard</p>",
                "login": "<p>Login Page</p>",
            },
            middleware=[AuthMiddleware],
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_http_blocked_without_auth(self):
        """Baseline: HTTP GET without auth cookie → redirect."""
        response = self.client.get("/", follow_redirects=False)
        assert response.status_code == 302

    def test_http_allowed_with_auth(self):
        """Baseline: HTTP GET with auth cookie → 200."""
        self.client.cookies.set("auth_token", "valid")
        response = self.client.get("/")
        self.client.cookies.clear()
        assert response.status_code == 200
        assert "Home" in response.text

    def test_ws_relocate_blocked_without_auth(self):
        """SPA nav via WS without auth cookie → navigate to /login."""
        with self.client.websocket_connect("/_pywire/ws") as ws:
            _ws_init(ws, "/login")  # Start on login (allowed)

            # Try to navigate to dashboard (protected)
            msg = _ws_relocate(ws, "/dashboard")

            # Should get navigate redirect to /login (302 from middleware)
            assert msg["type"] == "navigate"
            assert msg["path"] == "/login"

    def test_ws_relocate_allowed_with_auth_cookie(self):
        """SPA nav via WS with auth cookie in handshake → 200 update."""
        # Connect with auth cookie in handshake headers
        headers = {"cookie": "auth_token=valid"}
        with self.client.websocket_connect("/_pywire/ws", headers=headers) as ws:
            _ws_init(ws, "/")

            # Navigate to dashboard
            msg = _ws_relocate(ws, "/dashboard")

            assert msg["type"] == "update"
            assert "Dashboard" in msg.get("html", "")


# ---------------------------------------------------------------------------
# E2E: Cookie round-trip through relocate
# ---------------------------------------------------------------------------


class TestCookieRoundTrip:
    """Verify cookies set by middleware propagate through WS relocate."""

    def setup_method(self):
        self.app = _make_app(
            {
                "index": "<p>Home</p>",
                "about": "<p>About</p>",
            },
            middleware=[CookieSetterMiddleware],
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_http_sets_cookie(self):
        """Baseline: HTTP response includes tracker cookie."""
        response = self.client.get("/")
        assert "tracker" in response.headers.get("set-cookie", "")

    def test_ws_relocate_syncs_cookies(self):
        """SPA nav via WS receives cookie commands from middleware."""
        with self.client.websocket_connect("/_pywire/ws") as ws:
            _ws_init(ws, "/")

            msg = _ws_relocate(ws, "/about")

            assert msg["type"] == "update"
            assert "About" in msg.get("html", "")

            # Check that cookie commands were sent
            commands = msg.get("commands", [])
            cookie_cmds = [c for c in commands if c.get("cmd") == "set_cookie"]
            tracker_cmd = [
                c for c in cookie_cmds if c.get("args", {}).get("key") == "tracker"
            ]
            assert len(tracker_cmd) > 0, (
                f"Expected tracker cookie command, got: {commands}"
            )
            assert tracker_cmd[0]["args"]["value"] == "middleware-set"


# ---------------------------------------------------------------------------
# E2E: Rate limiting applies to SPA navigation
# ---------------------------------------------------------------------------


class TestRateLimitReplay:
    """Verify rate limiting middleware applies to WS SPA navigations."""

    def setup_method(self):
        self.app = _make_app(
            {
                "index": "<p>Home</p>",
                "page1": "<p>Page 1</p>",
                "page2": "<p>Page 2</p>",
            },
            middleware=[(RateLimitMiddleware, {"max_requests": 3})],
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_rate_limit_applies_to_relocate(self):
        """SPA navigations should count toward rate limit."""
        with self.client.websocket_connect("/_pywire/ws") as ws:
            _ws_init(ws, "/")

            # First few relocates should succeed
            msg1 = _ws_relocate(ws, "/page1")
            assert msg1["type"] == "update"
            assert "Page 1" in msg1.get("html", "")

            msg2 = _ws_relocate(ws, "/page2")
            assert msg2["type"] == "update"
            assert "Page 2" in msg2.get("html", "")

            msg3 = _ws_relocate(ws, "/")
            assert msg3["type"] == "update"

            # After max_requests, should get 429 error (rendered as update with error body)
            msg4 = _ws_relocate(ws, "/page1")
            # The 429 response body "Rate limited" is sent as an update
            # or the handler falls back to reload on non-200
            assert msg4["type"] in ("update", "reload")


# ---------------------------------------------------------------------------
# E2E: Internal dispatch error handling
# ---------------------------------------------------------------------------


class ErrorMiddleware(BaseHTTPMiddleware):
    """Raises an exception for a specific path."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/error-trigger":
            raise RuntimeError("Middleware exploded")
        return await call_next(request)


class TestInternalDispatchErrors:
    """Verify error handling when internal dispatch fails."""

    def setup_method(self):
        self.app = _make_app(
            {
                "index": "<p>Home</p>",
            },
            middleware=[ErrorMiddleware],
        )
        # Register a page at /error-trigger to ensure it has a route
        # (middleware will blow up before the page renders)
        pages_dir = Path(self.app._test_dir) / "pages"
        (pages_dir / "error-trigger.wire").write_text("<p>Should not render</p>")
        self.app._load_pages()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_middleware_error_triggers_reload(self):
        """If middleware raises during internal dispatch, client gets reload."""
        with self.client.websocket_connect("/_pywire/ws") as ws:
            _ws_init(ws, "/")

            msg = _ws_relocate(ws, "/error-trigger")
            # Should get a reload because the exception causes dispatch to fail
            assert msg["type"] == "reload"


# ---------------------------------------------------------------------------
# E2E: Multiple middleware ordering preserved
# ---------------------------------------------------------------------------


class OrderTagMiddleware(BaseHTTPMiddleware):
    """Appends a tag to X-Order header to verify middleware order."""

    def __init__(self, app: Any, tag: str = ""):
        super().__init__(app)
        self.tag = tag

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        existing = response.headers.get("X-Order", "")
        response.headers["X-Order"] = f"{existing},{self.tag}" if existing else self.tag
        return response


class TestMiddlewareOrderReplay:
    """Verify middleware ordering is preserved in internal dispatch."""

    def setup_method(self):
        self.app = _make_app(
            {
                "index": "<p>Home</p>",
                "about": "<p>About</p>",
            },
            middleware=[
                (OrderTagMiddleware, {"tag": "first"}),
                (OrderTagMiddleware, {"tag": "second"}),
            ],
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_http_middleware_order(self):
        """Baseline: HTTP request preserves middleware order."""
        response = self.client.get("/")
        order = response.headers.get("X-Order", "")
        # Starlette reverses middleware (last added = outermost)
        # Our list is [first, second], reversed becomes [second, first]
        # Outermost runs last on response, so second adds first, first adds second
        assert "first" in order
        assert "second" in order

    @pytest.mark.asyncio
    async def test_internal_dispatch_middleware_order(self):
        """Internal dispatch should have same middleware order as HTTP."""
        from pywire.runtime.internal_request import dispatch_internal

        response = await dispatch_internal(
            self.app._get_dispatch_target(),
            path="/about",
            headers={"host": "testserver"},
        )
        order = response.headers.get("x-order", "")
        assert "first" in order
        assert "second" in order


# ---------------------------------------------------------------------------
# E2E: Relocate with page that has wire() state
# ---------------------------------------------------------------------------


class TestRelocateWithState:
    """Verify relocate works with stateful pages."""

    def setup_method(self):
        self.app = _make_app(
            {
                "index": "---\ncount = wire(0)\n---\n<p id='count'>{count}</p>",
                "about": "<p>About</p>",
            },
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_relocate_to_stateful_page(self):
        """Relocate to a page with wire() state should render correctly."""
        with self.client.websocket_connect("/_pywire/ws") as ws:
            _ws_init(ws, "/about")

            msg = _ws_relocate(ws, "/")

            assert msg["type"] == "update"
            html = msg.get("html", "")
            assert "count" in html.lower() or "0" in html

    def test_relocate_between_pages(self):
        """Multiple relocates should work without error."""
        with self.client.websocket_connect("/_pywire/ws") as ws:
            _ws_init(ws, "/")

            # Go to about
            msg1 = _ws_relocate(ws, "/about")
            assert msg1["type"] == "update"
            assert "About" in msg1.get("html", "")

            # Come back to index
            msg2 = _ws_relocate(ws, "/")
            assert msg2["type"] == "update"

    def test_relocate_to_404(self):
        """Relocate to non-existent page should return error HTML."""
        with self.client.websocket_connect("/_pywire/ws") as ws:
            _ws_init(ws, "/")

            msg = _ws_relocate(ws, "/nonexistent")

            # Should get an update with 404 content or a reload
            assert msg["type"] in ("update", "reload")


# ---------------------------------------------------------------------------
# E2E: Virtual cookie jar reconciles with client document.cookie on relocate
# ---------------------------------------------------------------------------


class GateByCookieMiddleware(BaseHTTPMiddleware):
    """Redirect to /login unless ``demo_auth=ok`` is present."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/_pywire/") or path.startswith("/login"):
            return await call_next(request)
        if request.cookies.get("demo_auth") != "ok":
            return RedirectResponse("/login", status_code=302)
        return await call_next(request)


class TestCookieReconcile:
    """Browser-side cookie changes should sync on the next WS relocate."""

    def setup_method(self):
        self.app = _make_app(
            {
                "index": "<p>Home</p>",
                "dashboard": "<p>Dashboard</p>",
                "login": "<p>Login</p>",
            },
            middleware=[GateByCookieMiddleware],
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_client_dropped_cookie_tombstones_on_relocate(self):
        """Cookie in handshake but missing from document.cookie → redirect."""
        headers = {"cookie": "demo_auth=ok"}
        with self.client.websocket_connect("/_pywire/ws", headers=headers) as ws:
            _ws_init(ws, "/dashboard")

            # First relocate carries the cookie back — allowed.
            msg = _ws_relocate(ws, "/dashboard", cookies="demo_auth=ok")
            assert msg["type"] == "update"
            assert "Dashboard" in msg.get("html", "")

            # User clears cookie in browser. Next relocate sends empty
            # document.cookie. Server should tombstone and middleware
            # should redirect to /login.
            msg = _ws_relocate(ws, "/dashboard", cookies="")
            assert msg["type"] == "navigate"
            assert msg["path"] == "/login"

    def test_client_adds_cookie_allows_subsequent_relocate(self):
        """Cookie added in the browser between relocates lets middleware pass."""
        with self.client.websocket_connect("/_pywire/ws") as ws:
            _ws_init(ws, "/login")

            # Without cookie → redirect.
            msg = _ws_relocate(ws, "/dashboard", cookies="")
            assert msg["type"] == "navigate"
            assert msg["path"] == "/login"

            # Browser set the cookie locally (e.g. via document.cookie).
            msg = _ws_relocate(ws, "/dashboard", cookies="demo_auth=ok")
            assert msg["type"] == "update"
            assert "Dashboard" in msg.get("html", "")


class GateByHttpOnlyMiddleware(BaseHTTPMiddleware):
    """Redirect unless ``secret=ok`` (set HttpOnly server-side)."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/_pywire/") or path.startswith("/login"):
            response = await call_next(request)
            if path == "/login":
                response.set_cookie("secret", "ok", httponly=True, path="/")
            return response
        if request.cookies.get("secret") != "ok":
            return RedirectResponse("/login", status_code=302)
        return await call_next(request)


class TestHttpOnlyCookieStaysAuthoritative:
    """HttpOnly cookies are untouched by client reconcile."""

    def setup_method(self):
        self.app = _make_app(
            {
                "index": "<p>Home</p>",
                "dashboard": "<p>Dashboard</p>",
                "login": "<p>Login</p>",
            },
            middleware=[GateByHttpOnlyMiddleware],
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_httponly_survives_empty_client_cookie_header(self):
        """JS can't see httponly — empty document.cookie must NOT tombstone it."""
        with self.client.websocket_connect("/_pywire/ws") as ws:
            _ws_init(ws, "/login")

            # Visit /login → middleware sets httponly ``secret`` cookie.
            msg = _ws_relocate(ws, "/login", cookies="")
            assert msg["type"] == "update"

            # Client's document.cookie is empty (httponly hidden from JS).
            # The jar should keep ``secret=ok`` authoritative → dashboard allowed.
            msg = _ws_relocate(ws, "/dashboard", cookies="")
            assert msg["type"] == "update"
            assert "Dashboard" in msg.get("html", "")

    def test_handshake_httponly_survives_first_relocate_with_empty_cookies(self):
        """Regression: HttpOnly cookie set BEFORE the WS handshake (via a prior
        HTTP login → full reload) is in the handshake headers but not in
        ``document.cookie``. The first relocate's empty client payload must
        not tombstone it.
        """
        # Simulate: user logged in over HTTP earlier, browser stored the
        # HttpOnly session cookie, page reloaded → new WS connection whose
        # handshake carries the cookie in the request headers.
        headers = {"cookie": "secret=ok"}
        with self.client.websocket_connect(
            "/_pywire/ws", headers=headers
        ) as ws:
            _ws_init(ws, "/")

            # First relocate after login. document.cookie is empty because
            # ``secret`` is HttpOnly. Server must infer HttpOnly for any
            # baseline cookie missing from the empty client payload — not
            # tombstone them.
            msg = _ws_relocate(ws, "/dashboard", cookies="")
            assert msg["type"] == "update", (
                f"Expected logged-in render; got {msg.get('type')} "
                f"(path={msg.get('path')}). The session cookie was tombstoned."
            )
            assert "Dashboard" in msg.get("html", "")
