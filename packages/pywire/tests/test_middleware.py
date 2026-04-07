"""Tests for native ASGI middleware support on PyWire."""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.testclient import TestClient
from starlette.websockets import WebSocket

from pywire.runtime.app import PyWire


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class HeaderMiddleware(BaseHTTPMiddleware):
    """Adds a custom response header."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Custom-Header"] = "hello"
        return response


class OrderMiddleware(BaseHTTPMiddleware):
    """Appends its tag to a response header to verify ordering."""

    def __init__(self, app, tag: str = ""):
        super().__init__(app)
        self.tag = tag

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        existing = response.headers.get("X-Order", "")
        response.headers["X-Order"] = f"{existing},{self.tag}" if existing else self.tag
        return response


class SecretMiddleware(BaseHTTPMiddleware):
    """Middleware that requires a kwarg (secret_key)."""

    def __init__(self, app, secret_key: str = ""):
        super().__init__(app)
        self.secret_key = secret_key

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Has-Secret"] = "yes" if self.secret_key else "no"
        return response


def _make_app(**kwargs) -> PyWire:
    """Create a minimal PyWire app inside a temp directory with one page."""
    test_dir = tempfile.mkdtemp()
    pages_dir = Path(test_dir) / "pages"
    pages_dir.mkdir()
    # Minimal page that renders a simple response
    (pages_dir / "index.wire").write_text("<p>hello</p>")
    app = PyWire(pages_dir=str(pages_dir), **kwargs)
    app._test_dir = test_dir  # stash for cleanup
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConstructorMiddleware:
    def setup_method(self):
        self.app = _make_app(middleware=[HeaderMiddleware])
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_custom_header_appears(self):
        response = self.client.get("/")
        assert response.headers.get("X-Custom-Header") == "hello"


class TestAddMiddlewareMethod:
    def setup_method(self):
        self.app = _make_app()
        self.app.add_middleware(HeaderMiddleware)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_custom_header_via_add_middleware(self):
        response = self.client.get("/")
        assert response.headers.get("X-Custom-Header") == "hello"


class TestMiddlewareOrdering:
    """First middleware in the user's list should be outermost (processes response last)."""

    def setup_method(self):
        self.app = _make_app(
            middleware=[
                (OrderMiddleware, {"tag": "first"}),
                (OrderMiddleware, {"tag": "second"}),
            ]
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_ordering(self):
        response = self.client.get("/")
        order = response.headers.get("X-Order", "")
        # Inner middleware (second) processes response first, then outer (first)
        # appends. BaseHTTPMiddleware dispatch runs on the way out, so the
        # outermost middleware's dispatch runs LAST on the response.
        assert order == "second,first"


class TestTupleFormat:
    def setup_method(self):
        self.app = _make_app(
            middleware=[(SecretMiddleware, {"secret_key": "test-secret"})]
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_tuple_kwargs_passed(self):
        response = self.client.get("/")
        assert response.headers.get("X-Has-Secret") == "yes"


class TestWebSocketThroughMiddleware:
    def setup_method(self):
        self.app = _make_app(middleware=[HeaderMiddleware])
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.app._test_dir, ignore_errors=True)

    def test_websocket_connects(self):
        """WebSocket connections should pass through middleware without error."""
        # The PyWire WS endpoint is at /_pywire/ws
        # We just verify the connection is not rejected by middleware.
        # BaseHTTPMiddleware passes WebSocket scopes through untouched.
        with self.client.websocket_connect("/_pywire/ws") as ws:
            # Connection succeeded — that's the assertion.
            # Close cleanly; the server handler may send its own close.
            pass
