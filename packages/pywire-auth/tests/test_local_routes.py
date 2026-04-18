"""LocalIdP default route handlers (register / login / token / revoke)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pywire.auth import MemoryAuthChannel
from starlette.applications import Starlette
from starlette.testclient import TestClient

from pywire_auth import LocalIdP, MemoryAuthStore
from pywire_auth.local.routes import build_local_routes
from pywire_auth.routes import _RouteContext


class _MemStore:
    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Any]] = {}

    async def get(self, sid: str) -> Optional[Dict[str, Any]]:
        return self._data.get(sid)

    async def set(self, sid: str, data: Dict[str, Any], *, ttl: int = 0) -> None:
        self._data[sid] = dict(data)


class _SessionInjector:
    def __init__(self, app, session_id: Optional[str] = "sid-1"):
        self.app = app
        self.session_id = session_id

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.session_id is not None:
            scope["pywire_session_id"] = self.session_id
        await self.app(scope, receive, send)


def _build(
    *, session_id: Optional[str] = "sid-1", default_next: str = "/home"
) -> tuple[TestClient, _MemStore, LocalIdP, MemoryAuthChannel]:
    store = _MemStore()
    channel = MemoryAuthChannel()
    idp = LocalIdP(store=MemoryAuthStore(), secret="s" * 32)
    ctx = _RouteContext(
        providers={},
        session_store=store,
        session_ttl=1800,
        auth_channel=channel,
        default_next=default_next,
        on_login=None,
        on_logout=None,
    )
    app = Starlette(routes=build_local_routes(ctx, "/auth", idp))
    app.add_middleware(_SessionInjector, session_id=session_id)
    return TestClient(app, follow_redirects=False), store, idp, channel


def test_register_happy_path() -> None:
    client, store, _idp, _ = _build()
    resp = client.post(
        "/auth/local/register",
        data={"email": "a@b.c", "password": "pw", "name": "Alice"},
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/home"
    data = store._data["sid-1"]
    assert data["auth"]["name"] == "Alice"
    assert data["auth"]["user_id"].startswith("local:")


def test_register_with_role_and_email_verified() -> None:
    client, store, _idp, _ = _build()
    client.post(
        "/auth/local/register",
        data={
            "email": "a@b.c",
            "password": "pw",
            "name": "Alice",
            "role": "admin",
            "email_verified": "on",
        },
    )
    claims = dict(store._data["sid-1"]["auth"]["claims"])
    assert claims.get("role") == "admin"
    assert claims.get("email_verified") == "true"


def test_register_duplicate_email_redirects_with_error() -> None:
    client, _store, _idp, _ = _build()
    client.post("/auth/local/register", data={"email": "a@b.c", "password": "pw"})
    resp = client.post(
        "/auth/local/register", data={"email": "a@b.c", "password": "pw"}
    )
    assert resp.status_code == 303
    assert "error=exists" in resp.headers["location"]


def test_register_missing_fields_redirects_with_error() -> None:
    client, _store, _idp, _ = _build()
    resp = client.post("/auth/local/register", data={"email": "a@b.c"})
    assert resp.status_code == 303
    assert "error=missing" in resp.headers["location"]


def test_register_respects_next_query_param() -> None:
    client, _store, _idp, _ = _build()
    resp = client.post(
        "/auth/local/register?next=/dashboard",
        data={"email": "a@b.c", "password": "pw"},
    )
    assert resp.headers["location"] == "/dashboard"


def test_login_happy_path() -> None:
    client, store, idp, _ = _build()
    # Seed user.
    import asyncio

    asyncio.get_event_loop().run_until_complete(
        idp.create_user(email="a@b.c", password="pw", name="Alice")
    )
    resp = client.post(
        "/auth/local/login",
        data={"email": "a@b.c", "password": "pw"},
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/home"
    assert store._data["sid-1"]["auth"]["name"] == "Alice"


def test_login_invalid_credentials() -> None:
    client, _store, idp, _ = _build()
    import asyncio

    asyncio.get_event_loop().run_until_complete(
        idp.create_user(email="a@b.c", password="pw")
    )
    resp = client.post(
        "/auth/local/login", data={"email": "a@b.c", "password": "wrong"}
    )
    assert resp.status_code == 303
    assert "error=invalid" in resp.headers["location"]


def test_token_issues_jwt_for_authed_user() -> None:
    client, store, idp, _ = _build()
    client.post(
        "/auth/local/register",
        data={"email": "a@b.c", "password": "pw", "name": "Alice"},
    )
    resp = client.post("/auth/local/token")
    assert resp.status_code == 200
    body = resp.json()
    assert "token" in body
    assert body["decoded"]["iss"] == idp.issuer
    assert body["decoded"]["email"] == "a@b.c"


def test_token_requires_authentication() -> None:
    client, _store, _idp, _ = _build()
    resp = client.post("/auth/local/token")
    assert resp.status_code == 401


def test_verify_token_round_trip() -> None:
    client, _store, _idp, _ = _build()
    client.post(
        "/auth/local/register",
        data={"email": "a@b.c", "password": "pw"},
    )
    issued = client.post("/auth/local/token").json()["token"]
    resp = client.post("/auth/local/verify-token", json={"token": issued})
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["decoded"]["email"] == "a@b.c"


def test_verify_token_rejects_bad_token() -> None:
    client, _store, _idp, _ = _build()
    resp = client.post("/auth/local/verify-token", json={"token": "not.a.jwt"})
    assert resp.status_code == 200
    assert resp.json() == {"valid": False}


def test_verify_token_missing_token() -> None:
    client, _store, _idp, _ = _build()
    resp = client.post("/auth/local/verify-token", json={})
    assert resp.status_code == 400


def test_revoke_clears_session_and_fires_channel() -> None:
    client, store, _idp, channel = _build()
    client.post(
        "/auth/local/register",
        data={"email": "a@b.c", "password": "pw"},
    )
    principal_uid = store._data["sid-1"]["auth"]["user_id"]
    revoked = []

    async def fake_revoke(user_id: str) -> None:
        revoked.append(user_id)

    channel.revoke = fake_revoke  # type: ignore[assignment]

    resp = client.post("/auth/local/revoke")
    assert resp.status_code == 303
    assert "auth" not in store._data["sid-1"]
    assert revoked == [principal_uid]


def test_revoke_without_session_still_redirects() -> None:
    client, _store, _idp, _ = _build(session_id=None)
    resp = client.post("/auth/local/revoke")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/home"


def test_revoke_next_from_form() -> None:
    client, _store, _idp, _ = _build()
    client.post("/auth/local/register", data={"email": "a@b.c", "password": "pw"})
    resp = client.post("/auth/local/revoke", data={"next": "/goodbye"})
    assert resp.headers["location"] == "/goodbye"
