"""AuthMiddleware — cookie → principal → scope[user] + AuthContext."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from pywire.auth import (
    ANONYMOUS,
    AuthContext,
    Claim,
    ClaimsPrincipal,
    MemoryAuthChannel,
    PolicyEngine,
    get_auth_context,
    write_principal_to_session,
)
from pywire.runtime.session_middleware import _sign_session_id

from pywire_auth.middleware import AuthMiddleware

SECRET = "x" * 32


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _MemStore:
    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Any]] = {}

    async def get(self, sid: str) -> Optional[Dict[str, Any]]:
        return self._data.get(sid)

    async def set(self, sid: str, data: Dict[str, Any], *, ttl: int = 0) -> None:
        self._data[sid] = data


def _scope(cookie: Optional[str] = None) -> Dict[str, Any]:
    headers: List[tuple] = []
    if cookie:
        headers.append((b"cookie", cookie.encode("latin-1")))
    return {"type": "http", "headers": headers, "path": "/"}


def _make_mw(store: _MemStore, captured: List[Any]) -> AuthMiddleware:
    async def app(scope, receive, send):
        captured.append({"user": scope.get("user"), "ctx": get_auth_context()})

    return AuthMiddleware(
        app,
        session_store=store,
        secret_key=SECRET,
        policy_engine=PolicyEngine(),
        auth_channel=MemoryAuthChannel(),
    )


async def _noop_recv() -> dict:
    return {"type": "http.request"}


async def _noop_send(msg: dict) -> None:
    return None


def test_no_cookie_anonymous() -> None:
    store = _MemStore()
    captured: List[Any] = []
    mw = _make_mw(store, captured)
    _run(mw(_scope(), _noop_recv, _noop_send))
    assert captured[0]["user"] is ANONYMOUS
    assert captured[0]["ctx"].principal is ANONYMOUS


def test_invalid_signature_anonymous() -> None:
    store = _MemStore()
    captured: List[Any] = []
    mw = _make_mw(store, captured)
    # Unsigned / tampered cookie
    _run(mw(_scope("pywire_session=notvalid"), _noop_recv, _noop_send))
    assert captured[0]["user"] is ANONYMOUS


def test_valid_cookie_but_empty_session_anonymous() -> None:
    store = _MemStore()
    sid = "abc123"
    signed = _sign_session_id(sid, SECRET)
    captured: List[Any] = []
    mw = _make_mw(store, captured)
    _run(mw(_scope(f"pywire_session={signed}"), _noop_recv, _noop_send))
    assert captured[0]["user"] is ANONYMOUS


def test_session_with_principal_populates_scope() -> None:
    store = _MemStore()
    sid = "abc123"
    data: Dict[str, Any] = {}
    principal = ClaimsPrincipal(
        is_authenticated=True,
        name="Alice",
        user_id="local:1",
        claims=[Claim(type="role", value="admin")],
    )
    write_principal_to_session(data, principal)
    _run(store.set(sid, data))

    signed = _sign_session_id(sid, SECRET)
    captured: List[Any] = []
    mw = _make_mw(store, captured)
    _run(mw(_scope(f"pywire_session={signed}"), _noop_recv, _noop_send))

    user = captured[0]["user"]
    assert isinstance(user, ClaimsPrincipal)
    assert user.is_authenticated
    assert user.user_id == "local:1"
    assert user.has_claim("role", "admin")


def test_store_failure_falls_back_to_anonymous() -> None:
    class _BadStore:
        async def get(self, _sid):
            raise RuntimeError("db down")

    captured: List[Any] = []

    async def app(scope, receive, send):
        captured.append(scope.get("user"))

    mw = AuthMiddleware(
        app,
        session_store=_BadStore(),
        secret_key=SECRET,
        policy_engine=PolicyEngine(),
        auth_channel=MemoryAuthChannel(),
    )
    signed = _sign_session_id("abc", SECRET)
    _run(mw(_scope(f"pywire_session={signed}"), _noop_recv, _noop_send))
    assert captured[0] is ANONYMOUS


def test_context_reset_after_request() -> None:
    store = _MemStore()
    captured: List[Any] = []
    mw = _make_mw(store, captured)
    _run(mw(_scope(), _noop_recv, _noop_send))
    # ContextVar must be cleared after request
    assert get_auth_context() is None


def test_ctx_contains_engine_and_channel() -> None:
    store = _MemStore()
    captured: List[Any] = []
    engine = PolicyEngine()
    channel = MemoryAuthChannel()

    async def app(scope, receive, send):
        captured.append(get_auth_context())

    mw = AuthMiddleware(
        app,
        session_store=store,
        secret_key=SECRET,
        policy_engine=engine,
        auth_channel=channel,
    )
    _run(mw(_scope(), _noop_recv, _noop_send))
    ctx = captured[0]
    assert isinstance(ctx, AuthContext)
    assert ctx.engine is engine
    assert ctx.channel is channel


def test_non_http_scope_passthrough() -> None:
    store = _MemStore()
    hit: List[Any] = []

    async def app(scope, receive, send):
        hit.append(scope["type"])

    mw = AuthMiddleware(
        app,
        session_store=store,
        secret_key=SECRET,
        policy_engine=PolicyEngine(),
        auth_channel=MemoryAuthChannel(),
    )
    _run(mw({"type": "lifespan"}, _noop_recv, _noop_send))
    assert hit == ["lifespan"]
