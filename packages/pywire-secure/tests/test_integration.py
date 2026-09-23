"""Tests for ``connect_secure``.

These exercise the integration logic against a stub PyWire-shaped app.
A real PyWire app boot is exercised via ``test_e2e.py`` which requires
the full framework; tests here pin behaviour at the integration seam.
"""

from __future__ import annotations

from typing import Any

import pytest

from pywire_secure import (
    CSPBuilder,
    CSRFMiddleware,
    SecurityHeadersMiddleware,
    connect_secure,
)
from pywire_secure.config import resolve_config


class _StubApp:
    """Records add_middleware calls and exposes a fake _handle_request
    that connect_secure can monkey-patch."""

    def __init__(self, *, session_secret: str | None = None) -> None:
        self.middleware: list[tuple[type, dict]] = []
        self._session_secret = session_secret

        async def _handle_request(request: Any) -> Any:
            return None

        self._handle_request = _handle_request

    def add_middleware(self, cls: type, **kwargs: Any) -> None:
        self.middleware.append((cls, kwargs))


def _classes(app: _StubApp) -> list[type]:
    return [cls for cls, _ in app.middleware]


def test_default_install_adds_headers_and_csrf() -> None:
    app = _StubApp(session_secret="abcdef" * 6)
    connect_secure(app)
    classes = _classes(app)
    assert SecurityHeadersMiddleware in classes
    assert CSRFMiddleware in classes


def test_csrf_disabled_skips_csrf_middleware() -> None:
    app = _StubApp(session_secret="abcdef" * 6)
    connect_secure(app, csrf=False)
    assert CSRFMiddleware not in _classes(app)
    assert SecurityHeadersMiddleware in _classes(app)


def test_headers_disabled_skips_headers_middleware() -> None:
    app = _StubApp(session_secret="abcdef" * 6)
    connect_secure(app, headers=False)
    assert SecurityHeadersMiddleware not in _classes(app)
    assert CSRFMiddleware in _classes(app)


def test_csrf_without_secret_raises() -> None:
    """No PYWIRE_SESSION_SECRET, no app secret, csrf=True → fail loudly
    rather than silently mint tokens with a placeholder secret."""
    app = _StubApp(session_secret=None)
    with pytest.raises(RuntimeError, match="secret_key"):
        connect_secure(app)


def test_csrf_disabled_without_secret_is_fine() -> None:
    app = _StubApp(session_secret=None)
    connect_secure(app, csrf=False)
    assert CSRFMiddleware not in _classes(app)


def test_explicit_secret_overrides_app_secret() -> None:
    app = _StubApp(session_secret="from-app")
    connect_secure(app, secret_key="explicit-secret-32-bytes-padded-xx")
    csrf_kwargs = next(kw for cls, kw in app.middleware if cls is CSRFMiddleware)
    assert csrf_kwargs["secret_key"] == "explicit-secret-32-bytes-padded-xx"


def test_https_redirect_added_when_enabled() -> None:
    from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

    app = _StubApp(session_secret="abcdef" * 6)
    connect_secure(app, https_redirect=True)
    assert HTTPSRedirectMiddleware in _classes(app)


def test_hsts_value_built_from_config_flags() -> None:
    app = _StubApp(session_secret="abcdef" * 6)
    connect_secure(
        app,
        hsts=True,
        hsts_max_age=60,
        hsts_include_subdomains=True,
        hsts_preload=True,
    )
    headers_kwargs = next(
        kw for cls, kw in app.middleware if cls is SecurityHeadersMiddleware
    )
    assert headers_kwargs["hsts"] == "max-age=60; includeSubDomains; preload"


def test_hsts_disabled_results_in_none_value() -> None:
    app = _StubApp(session_secret="abcdef" * 6)
    connect_secure(app)
    headers_kwargs = next(
        kw for cls, kw in app.middleware if cls is SecurityHeadersMiddleware
    )
    assert headers_kwargs["hsts"] is None


def test_csp_builder_object_is_compiled() -> None:
    app = _StubApp(session_secret="abcdef" * 6)
    connect_secure(app, csp=CSPBuilder().default_src("'self'"))
    headers_kwargs = next(
        kw for cls, kw in app.middleware if cls is SecurityHeadersMiddleware
    )
    assert headers_kwargs["csp"] == "default-src 'self'"


def test_csp_string_passthrough() -> None:
    app = _StubApp(session_secret="abcdef" * 6)
    connect_secure(app, csp="default-src 'none'")
    headers_kwargs = next(
        kw for cls, kw in app.middleware if cls is SecurityHeadersMiddleware
    )
    assert headers_kwargs["csp"] == "default-src 'none'"


def test_handle_request_is_patched() -> None:
    app = _StubApp(session_secret="abcdef" * 6)
    original = app._handle_request
    connect_secure(app)
    assert app._handle_request is not original


def test_handle_request_not_patched_when_csrf_disabled() -> None:
    app = _StubApp(session_secret="abcdef" * 6)
    original = app._handle_request
    connect_secure(app, csrf=False)
    assert app._handle_request is original


def test_resolve_config_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """PYWIRE_SECURE_HEADERS=false should disable the headers default."""
    monkeypatch.setenv("PYWIRE_SECURE_HEADERS", "false")
    cfg = resolve_config()
    assert cfg.headers is False


def test_resolve_config_kwarg_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYWIRE_SECURE_CSRF", "false")
    cfg = resolve_config(csrf=True)
    assert cfg.csrf is True
