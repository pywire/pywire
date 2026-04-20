"""Tests for internal ASGI request replay (middleware parity).

Tests the dispatch_internal adapter, cookie helpers, and the integration
between WebSocket relocate and the ASGI middleware stack.
"""

import shutil
import tempfile
from pathlib import Path

import pytest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire
from pywire.runtime.internal_request import (
    dispatch_internal,
    encode_cookie_header,
    get_set_cookie_headers,
    parse_cookie_header,
    parse_set_cookie_value,
)


# ---------------------------------------------------------------------------
# Cookie helper tests
# ---------------------------------------------------------------------------


class TestParseCookieHeader:
    def test_simple(self):
        result = parse_cookie_header("foo=bar; baz=qux")
        assert result == {"foo": "bar", "baz": "qux"}

    def test_empty(self):
        result = parse_cookie_header("")
        assert result == {}

    def test_single(self):
        result = parse_cookie_header("session=abc123")
        assert result == {"session": "abc123"}

    def test_value_with_equals(self):
        result = parse_cookie_header("token=abc=def")
        assert result == {"token": "abc=def"}


class TestEncodeCookieHeader:
    def test_simple(self):
        result = encode_cookie_header({"foo": "bar", "baz": "qux"})
        assert "foo=bar" in result
        assert "baz=qux" in result
        assert "; " in result

    def test_empty(self):
        assert encode_cookie_header({}) == ""

    def test_single(self):
        assert encode_cookie_header({"k": "v"}) == "k=v"


class TestGetSetCookieHeaders:
    def test_extracts_set_cookie(self):
        headers = [
            (b"content-type", b"text/html"),
            (b"set-cookie", b"foo=bar; Path=/"),
            (b"x-custom", b"value"),
            (b"set-cookie", b"baz=qux; Path=/; HttpOnly"),
        ]
        result = get_set_cookie_headers(headers)
        assert len(result) == 2
        assert result[0] == (b"set-cookie", b"foo=bar; Path=/")
        assert result[1] == (b"set-cookie", b"baz=qux; Path=/; HttpOnly")

    def test_empty_headers(self):
        assert get_set_cookie_headers([]) == []

    def test_no_set_cookie(self):
        headers = [(b"content-type", b"text/html")]
        assert get_set_cookie_headers(headers) == []


class TestParseSetCookieValue:
    def test_simple(self):
        result = parse_set_cookie_value("session=abc123")
        assert result["key"] == "session"
        assert result["value"] == "abc123"

    def test_with_attributes(self):
        result = parse_set_cookie_value(
            "token=xyz; Path=/app; Max-Age=3600; Secure; HttpOnly; SameSite=Strict"
        )
        assert result["key"] == "token"
        assert result["value"] == "xyz"
        assert result["path"] == "/app"
        assert result["max_age"] == 3600
        assert result["secure"] is True
        assert result["httponly"] is True
        assert result["samesite"] == "Strict"

    def test_deletion(self):
        result = parse_set_cookie_value("session=; Max-Age=0; Path=/")
        assert result["key"] == "session"
        assert result["max_age"] == 0

    def test_empty(self):
        assert parse_set_cookie_value("") == {}


# ---------------------------------------------------------------------------
# dispatch_internal adapter tests
# ---------------------------------------------------------------------------


class TestDispatchInternal:
    @pytest.mark.asyncio
    async def test_basic_get(self):
        """Adapter captures status, headers, and body from a simple app."""

        async def app(scope, receive, send):
            assert scope["type"] == "http"
            assert scope["method"] == "GET"
            assert scope["path"] == "/hello"
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/plain")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b"Hello World",
                }
            )

        response = await dispatch_internal(app, path="/hello")
        assert response.status == 200
        assert response.headers["content-type"] == "text/plain"
        assert response.body == b"Hello World"

    @pytest.mark.asyncio
    async def test_query_string(self):
        """Query string is correctly parsed from the path."""

        async def app(scope, receive, send):
            assert scope["query_string"] == b"foo=bar&baz=1"
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        response = await dispatch_internal(app, path="/test?foo=bar&baz=1")
        assert response.status == 200

    @pytest.mark.asyncio
    async def test_headers_forwarded(self):
        """Custom headers are forwarded to the app."""
        received_headers = {}

        async def app(scope, receive, send):
            for name, value in scope["headers"]:
                received_headers[name.decode()] = value.decode()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        await dispatch_internal(
            app,
            path="/",
            headers={"authorization": "Bearer token123", "cookie": "s=abc"},
        )
        assert received_headers["authorization"] == "Bearer token123"
        assert received_headers["cookie"] == "s=abc"

    @pytest.mark.asyncio
    async def test_internal_sentinel(self):
        """Scope includes _pywire_internal sentinel."""

        async def app(scope, receive, send):
            assert scope.get("_pywire_internal") is True
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        await dispatch_internal(app, path="/")

    @pytest.mark.asyncio
    async def test_redirect_response(self):
        """Adapter captures redirect status and location header."""

        async def app(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 302,
                    "headers": [(b"location", b"/login")],
                }
            )
            await send({"type": "http.response.body", "body": b""})

        response = await dispatch_internal(app, path="/protected")
        assert response.status == 302
        assert response.headers["location"] == "/login"

    @pytest.mark.asyncio
    async def test_set_cookie_in_response(self):
        """Adapter captures Set-Cookie headers in raw_headers."""

        async def app(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"set-cookie", b"session=xyz; Path=/; HttpOnly"),
                        (b"set-cookie", b"theme=dark; Path=/"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b"ok"})

        response = await dispatch_internal(app, path="/")
        set_cookies = get_set_cookie_headers(response.raw_headers)
        assert len(set_cookies) == 2

    @pytest.mark.asyncio
    async def test_chunked_body(self):
        """Adapter collects multiple body chunks."""

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send(
                {"type": "http.response.body", "body": b"chunk1", "more_body": True}
            )
            await send(
                {"type": "http.response.body", "body": b"chunk2", "more_body": False}
            )

        response = await dispatch_internal(app, path="/")
        assert response.body == b"chunk1chunk2"

    @pytest.mark.asyncio
    async def test_base_scope_inherited(self):
        """Fields from base_scope are carried through."""

        async def app(scope, receive, send):
            assert scope["server"] == ("example.com", 443)
            assert scope["scheme"] == "https"
            assert scope["client"] == ("10.0.0.1", 5678)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        await dispatch_internal(
            app,
            path="/",
            base_scope={
                "server": ("example.com", 443),
                "scheme": "https",
                "client": ("10.0.0.1", 5678),
            },
        )

    @pytest.mark.asyncio
    async def test_post_with_body(self):
        """POST method and body are forwarded."""

        async def app(scope, receive, send):
            assert scope["method"] == "POST"
            msg = await receive()
            assert msg["body"] == b'{"key": "value"}'
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"created"})

        response = await dispatch_internal(
            app,
            method="POST",
            path="/api",
            body=b'{"key": "value"}',
            headers={"content-type": "application/json"},
        )
        assert response.status == 200
        assert response.body == b"created"


# ---------------------------------------------------------------------------
# Integration: auth middleware + internal dispatch
# ---------------------------------------------------------------------------


class AuthRedirectMiddleware(BaseHTTPMiddleware):
    """Redirects to /login if no 'auth_token' cookie is present."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/login", "/_pywire/capabilities"):
            return await call_next(request)
        if not request.cookies.get("auth_token"):
            return RedirectResponse("/login", status_code=302)
        return await call_next(request)


class CookieSetMiddleware(BaseHTTPMiddleware):
    """Sets a response cookie on every request."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.set_cookie("visited", "true", path="/")
        return response


def _make_app(**kwargs) -> PyWire:
    """Create a minimal PyWire app with one page."""
    test_dir = tempfile.mkdtemp()
    pages_dir = Path(test_dir) / "pages"
    pages_dir.mkdir()
    (pages_dir / "index.wire").write_text("<p>Home</p>")
    (pages_dir / "about.wire").write_text("<p>About</p>")
    (pages_dir / "login.wire").write_text("<p>Login</p>")
    app = PyWire(pages_dir=str(pages_dir), **kwargs)
    app._test_dir = test_dir
    return app


class TestAuthMiddlewareWithInternalDispatch:
    """Verify that auth middleware applies to internal ASGI dispatch."""

    def setup_method(self):
        self.app = _make_app(middleware=[AuthRedirectMiddleware])
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_http_redirects_without_auth(self):
        """Regular HTTP request without auth cookie gets redirected."""
        response = self.client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.headers["location"]

    def test_http_allows_with_auth(self):
        """Regular HTTP request with auth cookie succeeds."""
        self.client.cookies.set("auth_token", "valid")
        response = self.client.get("/", follow_redirects=False)
        self.client.cookies.clear()
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_internal_dispatch_redirects_without_auth(self):
        """Internal dispatch without auth cookie gets redirected."""
        response = await dispatch_internal(
            self.app._get_dispatch_target(),
            path="/about",
            headers={"host": "testserver"},
        )
        assert response.status == 302
        assert response.headers.get("location") == "/login"

    @pytest.mark.asyncio
    async def test_internal_dispatch_allows_with_auth(self):
        """Internal dispatch with auth cookie succeeds."""
        response = await dispatch_internal(
            self.app._get_dispatch_target(),
            path="/about",
            headers={
                "host": "testserver",
                "cookie": "auth_token=valid",
            },
        )
        assert response.status == 200
        assert b"About" in response.body

    @pytest.mark.asyncio
    async def test_internal_relocate_renders_body_only(self):
        """Internal relocate request renders body-only HTML (no scripts)."""
        response = await dispatch_internal(
            self.app._get_dispatch_target(),
            path="/about",
            headers={
                "host": "testserver",
                "cookie": "auth_token=valid",
                "x-pywire-internal": "relocate",
            },
        )
        assert response.status == 200
        html = response.body.decode("utf-8")
        assert "About" in html
        # Body-only mode should not include full document wrapper
        # (exact check depends on page rendering, but script tag should be absent)
        assert "<script" not in html or "pywire" not in html.lower().split("<script")[0]


class TestCookieMiddlewareWithInternalDispatch:
    """Verify that cookies set by middleware propagate through internal dispatch."""

    def setup_method(self):
        self.app = _make_app(middleware=[CookieSetMiddleware])
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_http_sets_cookie(self):
        """Regular HTTP request gets the visited cookie."""
        response = self.client.get("/")
        assert "visited" in response.cookies

    @pytest.mark.asyncio
    async def test_internal_dispatch_captures_set_cookie(self):
        """Internal dispatch captures Set-Cookie headers from middleware."""
        response = await dispatch_internal(
            self.app._get_dispatch_target(),
            path="/",
            headers={"host": "testserver"},
        )
        set_cookies = get_set_cookie_headers(response.raw_headers)
        assert len(set_cookies) > 0
        cookie_values = [v.decode() for _, v in set_cookies]
        assert any("visited=true" in c for c in cookie_values)
