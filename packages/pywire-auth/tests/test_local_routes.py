"""LocalIdP default route handlers (register / login / token / revoke)."""

from __future__ import annotations

import asyncio
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
        # The browser's session id; login and logout rotate it.
        self.jar: Dict[str, Optional[str]] = {"sid": None}

    async def get(self, sid: str) -> Optional[Dict[str, Any]]:
        return self._data.get(sid)

    async def set(self, sid: str, data: Dict[str, Any], *, ttl: int = 0) -> None:
        self._data[sid] = dict(data)

    async def delete(self, sid: str) -> None:
        self._data.pop(sid, None)

    def current(self) -> Dict[str, Any]:
        """The session the test browser now holds."""
        return self._data[self.jar["sid"]]


class _SessionInjector:
    """Stands in for SessionMiddleware; follows session id rotation."""

    def __init__(self, app, jar: Dict[str, Optional[str]]):
        self.app = app
        self.jar = jar

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.jar["sid"] is not None:
            scope["pywire_session_id"] = self.jar["sid"]
        await self.app(scope, receive, send)
        if scope["type"] == "http":
            self.jar["sid"] = scope.get("pywire_session_id")


def _build(
    *, session_id: Optional[str] = "sid-1", default_next: str = "/home"
) -> tuple[TestClient, _MemStore, LocalIdP, MemoryAuthChannel]:
    store = _MemStore()
    store.jar["sid"] = session_id
    channel = MemoryAuthChannel()
    idp = LocalIdP(store=MemoryAuthStore(), secret="test-signing-key-0123456789abcdef")
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
    app.add_middleware(_SessionInjector, jar=store.jar)
    return TestClient(app, follow_redirects=False), store, idp, channel


def test_register_happy_path() -> None:
    client, store, _idp, _ = _build()
    resp = client.post(
        "/auth/local/register",
        data={"email": "a@b.c", "password": "pw", "name": "Alice"},
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/home"
    data = store.current()
    assert data["auth"]["name"] == "Alice"
    assert data["auth"]["user_id"].startswith("local:")


def test_register_ignores_claims_posted_in_the_form() -> None:
    """A visitor cannot grant themselves a role or a verified email."""
    client, store, idp, _ = _build()
    resp = client.post(
        "/auth/local/register",
        data={
            "email": "a@b.c",
            "password": "pw",
            "name": "Alice",
            "role": "admin",
            "email_verified": "on",
            "claims": "role=admin",
        },
    )
    assert resp.status_code == 303
    auth = store.current()["auth"]
    claim_types = {c_type for c_type, _value in auth["claims"]}
    assert "role" not in claim_types
    assert "email_verified" not in claim_types

    # Nor on the stored user: the next login must not pick them up either.
    principal = asyncio.run(idp.principal_for_user(auth["user_id"].split(":", 1)[1]))
    assert principal is not None
    assert not principal.has_claim("role")
    assert not principal.has_claim("email_verified")


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

    asyncio.run(idp.create_user(email="a@b.c", password="pw", name="Alice"))
    resp = client.post(
        "/auth/local/login",
        data={"email": "a@b.c", "password": "pw"},
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/home"
    assert store.current()["auth"]["name"] == "Alice"


def test_login_invalid_credentials() -> None:
    client, _store, idp, _ = _build()
    import asyncio

    asyncio.run(idp.create_user(email="a@b.c", password="pw"))
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
    principal_uid = store.current()["auth"]["user_id"]
    revoked = []

    async def fake_revoke(user_id: str) -> None:
        revoked.append(user_id)

    channel.revoke = fake_revoke  # type: ignore[assignment]

    resp = client.post("/auth/local/revoke")
    assert resp.status_code == 303
    assert "auth" not in store.current()
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


def test_login_and_logout_rotate_session_id() -> None:
    client, store, idp, _ = _build()
    import asyncio

    asyncio.run(idp.create_user(email="a@b.c", password="pw"))
    store._data["sid-1"] = {"cart": [1]}
    client.post("/auth/local/login", data={"email": "a@b.c", "password": "pw"})
    signed_in = store.jar["sid"]
    assert signed_in != "sid-1" and "sid-1" not in store._data
    assert store.current()["cart"] == [1]  # the rest of the session moves along
    client.post("/auth/local/revoke")
    assert store.jar["sid"] != signed_in and signed_in not in store._data
    assert "auth" not in store.current()


def test_redirect_targets_stay_on_site() -> None:
    client, _store, idp, _ = _build()
    import asyncio

    asyncio.run(idp.create_user(email="a@b.c", password="pw"))
    for bad in ("https://evil.example", "//evil.example", "/\\evil.example"):
        resp = client.post(
            "/auth/local/login",
            data={"email": "a@b.c", "password": "x", "error_next": bad},
        )
        assert "evil" not in resp.headers["location"]
        resp = client.post(
            "/auth/local/login",
            params={"next": bad},
            data={"email": "a@b.c", "password": "pw"},
        )
        assert resp.headers["location"] == "/home"
        resp = client.post("/auth/local/revoke", data={"next": bad})
        assert resp.headers["location"] == "/home"
    resp = client.post(
        "/auth/local/login",
        data={"email": "a@b.c", "password": "x"},
        headers={"referer": "http://testserver//evil.example/x"},
    )
    assert "evil" not in resp.headers["location"]


def test_cross_site_posts_refused() -> None:
    client, store, idp, _ = _build()
    import asyncio

    asyncio.run(idp.create_user(email="a@b.c", password="pw"))
    for path, data in (
        ("/auth/local/login", {"email": "a@b.c", "password": "pw"}),
        ("/auth/local/register", {"email": "b@b.c", "password": "pw"}),
        ("/auth/local/revoke", {}),
    ):
        resp = client.post(path, data=data, headers={"origin": "https://evil.example"})
        assert resp.status_code == 403
        resp = client.post(path, data=data, headers={"sec-fetch-site": "same-site"})
        assert resp.status_code == 403
    assert store.jar["sid"] == "sid-1"


def test_login_email_is_case_insensitive() -> None:
    client, store, idp, _ = _build()
    import asyncio

    asyncio.run(idp.create_user(email="Alice@Example.com", password="pw"))
    resp = client.post(
        "/auth/local/login", data={"email": " alice@EXAMPLE.com ", "password": "pw"}
    )
    assert resp.headers["location"] == "/home"
    resp = client.post(
        "/auth/local/register", data={"email": "ALICE@example.com", "password": "pw"}
    )
    assert "error=exists" in resp.headers["location"]


def test_login_is_throttled() -> None:
    from pywire_auth.local.throttle import Throttle

    client, _store, idp, _ = _build()
    idp.throttle = Throttle(limit=3, window=60)
    import asyncio

    asyncio.run(idp.create_user(email="a@b.c", password="pw"))
    for _ in range(3):
        resp = client.post(
            "/auth/local/login", data={"email": "a@b.c", "password": "x"}
        )
        assert "error=invalid" in resp.headers["location"]
    # Even the right password is refused until the window passes.
    resp = client.post("/auth/local/login", data={"email": "a@b.c", "password": "pw"})
    assert "error=throttled" in resp.headers["location"]


def test_register_is_throttled_per_client() -> None:
    from pywire_auth.local.throttle import Throttle

    client, _store, idp, _ = _build()
    idp.throttle = Throttle(limit=2, window=60)
    for i in range(2):
        resp = client.post(
            "/auth/local/register", data={"email": f"u{i}@b.c", "password": "pw"}
        )
        assert resp.headers["location"] == "/home"
    resp = client.post(
        "/auth/local/register", data={"email": "u9@b.c", "password": "pw"}
    )
    assert "error=throttled" in resp.headers["location"]
