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
    returned = connect_auth(app, providers=[_FakeProvider()], policy_engine=engine)
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


def _added_by_class(app: _FakePyWireApp, cls: Any) -> Dict[str, Any]:
    for added_cls, kwargs in app._added:
        if added_cls is cls:
            return kwargs
    raise AssertionError(f"{cls.__name__} was not added")


def test_middleware_installed_with_secret() -> None:
    app = _FakePyWireApp(session_secret="k" * 32)
    engine = connect_auth(app, providers=[_FakeProvider()])
    kwargs = _added_by_class(app, AuthMiddleware)
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
    connect_auth(app, providers=[_FakeProvider()], secret_key="explicit-key")
    kwargs = _added_by_class(app, AuthMiddleware)
    assert kwargs["secret_key"] == "explicit-key"


def test_env_secret_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _FakePyWireApp()
    monkeypatch.setenv("PYWIRE_SESSION_SECRET", "from-env")
    from pywire import config as pywire_config

    pywire_config.reload()
    connect_auth(app, providers=[_FakeProvider()])
    kwargs = _added_by_class(app, AuthMiddleware)
    assert kwargs["secret_key"] == "from-env"


def test_session_ttl_override() -> None:
    app = _FakePyWireApp(session_secret="k" * 32, session_ttl=60)
    connect_auth(app, providers=[_FakeProvider()], session_ttl=900)
    # Smoke: didn't raise, AuthMiddleware installed with the overridden store.
    auth_kwargs = _added_by_class(app, AuthMiddleware)
    assert auth_kwargs["session_store"] is app.session_store


def test_session_middleware_auto_installed_when_missing() -> None:
    from pywire.runtime.session_middleware import SessionMiddleware

    app = _FakePyWireApp(session_secret="k" * 32)
    connect_auth(app, providers=[_FakeProvider()])
    kwargs = _added_by_class(app, SessionMiddleware)
    assert kwargs["secret_key"] == "k" * 32
    assert kwargs["session_store"] is app.session_store


def test_session_middleware_skipped_when_present() -> None:
    from pywire.runtime.session_middleware import SessionMiddleware

    app = _FakePyWireApp(session_secret="k" * 32)
    # Pre-install SessionMiddleware the way a non-interactive PyWire would.
    app.add_middleware(
        SessionMiddleware,
        session_store=app.session_store,
        session_ttl=1800,
        secret_key="k" * 32,
    )
    connect_auth(app, providers=[_FakeProvider()])
    session_mws = [cls for cls, _ in app._added if cls is SessionMiddleware]
    assert len(session_mws) == 1  # only the pre-existing one


def test_local_routes_mounted_when_local_idp_passed() -> None:
    from pywire_auth import LocalIdP, MemoryAuthStore

    app = _FakePyWireApp(session_secret="k" * 32)
    idp = LocalIdP(store=MemoryAuthStore(), secret="s" * 32)
    connect_auth(app, local_idp=idp)
    paths = [getattr(r, "path", "") for r in app.app.router.routes]
    assert "/auth/local/register" in paths
    assert "/auth/local/login" in paths
    assert "/auth/local/token" in paths
    assert "/auth/local/verify-token" in paths
    assert "/auth/local/revoke" in paths


def test_local_routes_absent_without_local_idp() -> None:
    app = _FakePyWireApp(session_secret="k" * 32)
    connect_auth(app, providers=[_FakeProvider()])
    paths = [getattr(r, "path", "") for r in app.app.router.routes]
    assert "/auth/local/register" not in paths


def test_app_state_populated() -> None:
    from pywire_auth import LocalIdP, MemoryAuthStore

    app = _FakePyWireApp(session_secret="k" * 32)
    idp = LocalIdP(store=MemoryAuthStore(), secret="s" * 32)
    engine = connect_auth(app, providers=[_FakeProvider()], local_idp=idp)
    assert app.app.state.auth_engine is engine
    assert app.app.state.local_idp is idp
    assert app.app.state.auth_store is idp.store
    assert app.app.state.auth_providers == ["fake"]
