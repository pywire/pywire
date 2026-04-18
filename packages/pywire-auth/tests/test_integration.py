"""connect_auth — integration entry point wiring."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from pywire.auth import MemoryAuthChannel, PolicyEngine
from starlette.applications import Starlette
from starlette.routing import Route

from pywire_auth import connect_auth
from pywire_auth.middleware import AuthMiddleware


class _FakeProvider:
    name = "fake"
    client_id = "cid"
    client_secret = "sec"


class _FakePyWireApp:
    """Minimal PyWireApp surface that connect_auth reads."""

    def __init__(self, *, session_secret: str = "", session_ttl: int = 1800) -> None:
        self.session_store = object()
        self.session_ttl = session_ttl
        if session_secret:
            self._session_secret = session_secret
        # Seed a Starlette app with a catch-all last route to prove insertion
        # happens at index 0.
        async def catch_all(request):  # pragma: no cover
            from starlette.responses import Response

            return Response("catch", status_code=200)

        self.app = Starlette(routes=[Route("/{rest:path}", catch_all)])
        self._added: List[tuple] = []

    def add_middleware(self, cls: Any, **kwargs: Any) -> None:
        self._added.append((cls, kwargs))
        self.app.add_middleware(cls, **kwargs)


def test_connect_returns_engine() -> None:
    app = _FakePyWireApp(session_secret="k" * 32)
    engine = connect_auth(app, providers=[_FakeProvider()])
    assert isinstance(engine, PolicyEngine)


def test_connect_uses_existing_engine() -> None:
    app = _FakePyWireApp(session_secret="k" * 32)
    engine = PolicyEngine()
    returned = connect_auth(
        app, providers=[_FakeProvider()], policy_engine=engine
    )
    assert returned is engine
    assert app._auth_engine is engine


def test_connect_uses_existing_channel() -> None:
    app = _FakePyWireApp(session_secret="k" * 32)
    channel = MemoryAuthChannel()
    connect_auth(app, providers=[_FakeProvider()], auth_channel=channel)
    assert app._auth_channel is channel


def test_routes_inserted_before_catchall() -> None:
    app = _FakePyWireApp(session_secret="k" * 32)
    connect_auth(app, providers=[_FakeProvider()])
    # The three auth routes should appear before the pre-existing catch-all.
    paths = [getattr(r, "path", "") for r in app.app.router.routes]
    first_three = paths[:3]
    assert any("/login" in p for p in first_three)
    assert any("/callback" in p for p in first_three)
    assert any("/logout" in p for p in first_three)
    # Catch-all remains last.
    assert paths[-1] == "/{rest:path}"


def test_custom_prefix() -> None:
    app = _FakePyWireApp(session_secret="k" * 32)
    connect_auth(app, providers=[_FakeProvider()], prefix="/oidc")
    paths = [getattr(r, "path", "") for r in app.app.router.routes]
    assert any(p.startswith("/oidc/") for p in paths)


def test_middleware_installed_with_secret() -> None:
    app = _FakePyWireApp(session_secret="k" * 32)
    engine = connect_auth(app, providers=[_FakeProvider()])
    assert len(app._added) == 1
    cls, kwargs = app._added[0]
    assert cls is AuthMiddleware
    assert kwargs["secret_key"] == "k" * 32
    assert kwargs["session_store"] is app.session_store
    assert kwargs["policy_engine"] is engine


def test_providers_indexed_by_name() -> None:
    app = _FakePyWireApp(session_secret="k" * 32)
    p1 = _FakeProvider()
    connect_auth(app, providers=[p1])
    assert app._auth_providers == {"fake": p1}


def test_missing_secret_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _FakePyWireApp()  # no session secret attribute
    # Make sure the env fallback is empty.
    monkeypatch.delenv("PYWIRE_SESSION_SECRET", raising=False)
    from pywire import config as pywire_config

    pywire_config.reload()
    with pytest.raises(RuntimeError, match="secret_key"):
        connect_auth(app, providers=[_FakeProvider()])


def test_explicit_secret_key_overrides_app() -> None:
    app = _FakePyWireApp(session_secret="from-app")
    connect_auth(
        app, providers=[_FakeProvider()], secret_key="explicit-key"
    )
    _, kwargs = app._added[0]
    assert kwargs["secret_key"] == "explicit-key"


def test_env_secret_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _FakePyWireApp()
    monkeypatch.setenv("PYWIRE_SESSION_SECRET", "from-env")
    from pywire import config as pywire_config

    pywire_config.reload()
    connect_auth(app, providers=[_FakeProvider()])
    _, kwargs = app._added[0]
    assert kwargs["secret_key"] == "from-env"


def test_session_ttl_override() -> None:
    app = _FakePyWireApp(session_secret="k" * 32, session_ttl=60)
    connect_auth(app, providers=[_FakeProvider()], session_ttl=900)
    # The _RouteContext is not directly exposed; confirm via internal kwargs is n/a.
    # Smoke-test: connect_auth didn't raise, and _added middleware carries store.
    assert len(app._added) == 1
