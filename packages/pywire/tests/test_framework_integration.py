"""Tests for framework integration (as_asgi, fallthrough_404).

Tests mounting PyWire inside a host Starlette app (which is what FastAPI
does under the hood). Verifies path prefix handling, fallthrough 404,
middleware parity, and root app reference.
"""

import shutil
import tempfile
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire
from pywire.runtime.internal_request import dispatch_internal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pywire(**kwargs) -> PyWire:
    """Create a minimal PyWire app."""
    test_dir = tempfile.mkdtemp()
    pages_dir = Path(test_dir) / "pages"
    pages_dir.mkdir()
    (pages_dir / "index.wire").write_text("<p>PyWire Home</p>")
    (pages_dir / "dashboard.wire").write_text("<p>Dashboard</p>")
    app = PyWire(pages_dir=str(pages_dir), **kwargs)
    app._test_dir = test_dir
    return app


def _make_host_app(pywire: PyWire, mount_path: str = "/") -> Starlette:
    """Create a host Starlette app with PyWire mounted + API routes."""

    async def api_hello(request: Request) -> JSONResponse:
        return JSONResponse({"message": "hello from API"})

    async def api_health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    routes = [
        Route("/api/hello", api_hello),
        Route("/api/health", api_health),
        Mount(mount_path, app=pywire.as_asgi()),
    ]

    return Starlette(routes=routes)


# ---------------------------------------------------------------------------
# as_asgi() basic tests
# ---------------------------------------------------------------------------


class TestAsAsgi:
    def setup_method(self):
        self.pywire = _make_pywire()

    def teardown_method(self):
        shutil.rmtree(self.pywire._test_dir, ignore_errors=True)

    def test_returns_self(self):
        """as_asgi() should return the PyWire instance itself."""
        assert self.pywire.as_asgi() is self.pywire

    def test_standalone_still_works(self):
        """PyWire should still work standalone after calling as_asgi()."""
        client = TestClient(self.pywire.as_asgi(), raise_server_exceptions=False)
        response = client.get("/")
        assert response.status_code == 200
        assert "PyWire Home" in response.text


# ---------------------------------------------------------------------------
# Mounting in host app
# ---------------------------------------------------------------------------


class TestMountAtRoot:
    def setup_method(self):
        self.pywire = _make_pywire(fallthrough_404=True)
        self.host = _make_host_app(self.pywire, mount_path="/")
        self.client = TestClient(self.host, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.pywire._test_dir, ignore_errors=True)

    def test_api_routes_work(self):
        """Host API routes should still be accessible."""
        response = self.client.get("/api/hello")
        assert response.status_code == 200
        assert response.json() == {"message": "hello from API"}

    def test_pywire_pages_render(self):
        """PyWire pages should render when mounted at root."""
        response = self.client.get("/")
        assert response.status_code == 200
        assert "PyWire Home" in response.text

    def test_pywire_dashboard(self):
        response = self.client.get("/dashboard")
        assert response.status_code == 200
        assert "Dashboard" in response.text

    def test_unknown_path_fallthrough(self):
        """Unmatched paths should return 404 from PyWire fallthrough."""
        response = self.client.get("/nonexistent")
        assert response.status_code == 404


class TestMountAtPrefix:
    def setup_method(self):
        self.pywire = _make_pywire(fallthrough_404=True)
        self.host = _make_host_app(self.pywire, mount_path="/app")
        self.client = TestClient(self.host, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.pywire._test_dir, ignore_errors=True)

    def test_api_routes_work(self):
        response = self.client.get("/api/hello")
        assert response.status_code == 200

    def test_pywire_at_prefix(self):
        """PyWire pages should render at the mount prefix."""
        response = self.client.get("/app/")
        assert response.status_code == 200
        assert "PyWire Home" in response.text

    def test_pywire_subpage_at_prefix(self):
        response = self.client.get("/app/dashboard")
        assert response.status_code == 200
        assert "Dashboard" in response.text

    def test_root_not_pywire(self):
        """Root path should not serve PyWire pages."""
        response = self.client.get("/")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Fallthrough 404
# ---------------------------------------------------------------------------


class TestFallthrough404:
    def test_fallthrough_enabled(self):
        """With fallthrough_404=True, unmatched paths return bare 404."""
        pywire = _make_pywire(fallthrough_404=True)
        client = TestClient(pywire, raise_server_exceptions=False)
        response = client.get("/nonexistent")
        assert response.status_code == 404
        # Should be a bare response, not PyWire's error page
        assert "PyWire" not in response.text
        assert len(response.text) == 0
        shutil.rmtree(pywire._test_dir, ignore_errors=True)

    def test_fallthrough_disabled(self):
        """With fallthrough_404=False (default), render PyWire error page."""
        pywire = _make_pywire(fallthrough_404=False)
        client = TestClient(pywire, raise_server_exceptions=False)
        response = client.get("/nonexistent")
        assert response.status_code == 404
        # Should have PyWire's error page content
        assert response.text  # non-empty
        shutil.rmtree(pywire._test_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# as_asgi(host) — root app reference for internal dispatch
# ---------------------------------------------------------------------------


class HostHeaderMiddleware(BaseHTTPMiddleware):
    """Adds a custom header to verify host middleware ran."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Host-Middleware"] = "applied"
        return response


class TestAsAsgiHost:
    def setup_method(self):
        self.pywire = _make_pywire(fallthrough_404=True)

    def teardown_method(self):
        shutil.rmtree(self.pywire._test_dir, ignore_errors=True)

    def test_as_asgi_with_host_sets_root_app(self):
        """as_asgi(host) should store the root app reference."""
        host = Starlette()
        self.pywire.as_asgi(host)
        assert self.pywire._root_app is host

    def test_as_asgi_without_host_no_root_app(self):
        """as_asgi() without host should leave _root_app as None."""
        self.pywire.as_asgi()
        assert self.pywire._root_app is None

    def test_as_asgi_returns_self(self):
        """as_asgi() should return self for mounting."""
        host = Starlette()
        result = self.pywire.as_asgi(host)
        assert result is self.pywire

    def test_dispatch_target_uses_root(self):
        """After as_asgi(host), _get_dispatch_target should return host."""
        host = Starlette()
        self.pywire.as_asgi(host)
        assert self.pywire._get_dispatch_target() is host

    def test_dispatch_target_without_host(self):
        """Without host, _get_dispatch_target returns Starlette app."""
        assert self.pywire._get_dispatch_target() is self.pywire.app

    @pytest.mark.asyncio
    async def test_internal_dispatch_through_host_middleware(self):
        """Internal dispatch should go through host middleware when mounted."""
        host = Starlette(
            routes=[
                Mount("/", app=self.pywire.as_asgi()),
            ],
        )
        host.add_middleware(HostHeaderMiddleware)
        # Set host after construction (can't reference host in its own constructor)
        self.pywire.as_asgi(host)

        response = await dispatch_internal(
            self.pywire._get_dispatch_target(),
            path="/",
            headers={"host": "testserver"},
        )
        assert response.status == 200
        assert response.headers.get("x-host-middleware") == "applied"


# ---------------------------------------------------------------------------
# Capabilities endpoint when mounted
# ---------------------------------------------------------------------------


class TestCapabilitiesMounted:
    def setup_method(self):
        self.pywire = _make_pywire(fallthrough_404=True)
        self.host = _make_host_app(self.pywire, mount_path="/app")
        self.client = TestClient(self.host, raise_server_exceptions=False)

    def teardown_method(self):
        shutil.rmtree(self.pywire._test_dir, ignore_errors=True)

    def test_capabilities_at_prefix(self):
        """Capabilities endpoint should work at the mount prefix."""
        response = self.client.get("/app/_pywire/capabilities")
        assert response.status_code == 200
        data = response.json()
        assert "websocket" in data["transports"]
        assert data["interactive"] is True
