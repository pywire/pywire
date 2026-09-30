"""OAuth login / callback / logout route handlers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import pytest

from pywire.auth import Claim, ClaimsPrincipal, MemoryAuthChannel
from starlette.applications import Starlette
from starlette.testclient import TestClient

from pywire_auth.routes import STATE_KEY, _RouteContext, build_routes, pkce_challenge


class _MemStore:
    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Any]] = {}

    async def get(self, sid: str) -> Optional[Dict[str, Any]]:
        return self._data.get(sid)

    async def set(self, sid: str, data: Dict[str, Any], *, ttl: int = 0) -> None:
        self._data[sid] = dict(data)

    async def delete(self, sid: str) -> None:
        self._data.pop(sid, None)


class _FakeProvider:
    """Captures authorize_url inputs; exchange_code returns a scripted principal."""

    name = "fake"

    def __init__(
        self,
        *,
        principal: Optional[ClaimsPrincipal] = None,
        token_data: Optional[Dict[str, Any]] = None,
        raises: bool = False,
    ) -> None:
        self.principal = principal or ClaimsPrincipal(
            is_authenticated=True,
            name="A",
            user_id="fake:1",
            claims=[Claim(type="email", value="a@b.c")],
        )
        self.token_data = token_data or {"access_token": "at"}
        self.raises = raises
        self.authorize_calls: List[Dict[str, str]] = []
        self.exchange_calls: List[Dict[str, str]] = []

    async def authorize_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str:
        self.authorize_calls.append(
            {
                "redirect_uri": redirect_uri,
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
            }
        )
        return f"https://idp.example/authorize?state={state}"

    async def exchange_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        state: str,
        nonce: str,
        code_verifier: str,
    ) -> Tuple[ClaimsPrincipal, Dict[str, Any]]:
        self.exchange_calls.append(
            {
                "code": code,
                "redirect_uri": redirect_uri,
                "state": state,
                "nonce": nonce,
                "code_verifier": code_verifier,
            }
        )
        if self.raises:
            raise RuntimeError("exchange exploded")
        return self.principal, self.token_data


class _SessionInjector:
    """Stands in for SessionMiddleware: the jar holds the browser's session id.

    A route that rotates the session id (login, logout) changes the jar, as
    the new cookie would.
    """

    def __init__(self, app, jar: Dict[str, Optional[str]]):
        self.app = app
        self.jar = jar

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.jar["sid"] is not None:
            scope["pywire_session_id"] = self.jar["sid"]
        await self.app(scope, receive, send)
        if scope["type"] == "http":
            self.jar["sid"] = scope.get("pywire_session_id")


def _session(app: Starlette, store: _MemStore) -> Dict[str, Any]:
    """The session the test browser now holds."""
    return store._data[app.state.jar["sid"]]


def _build_app(
    *,
    provider: _FakeProvider,
    store: _MemStore,
    channel: MemoryAuthChannel,
    session_id: Optional[str] = "sid-1",
    default_next: str = "/home",
) -> Starlette:
    ctx = _RouteContext(
        providers={provider.name: provider},
        session_store=store,
        session_ttl=1800,
        auth_channel=channel,
        default_next=default_next,
        on_login=None,
        on_logout=None,
    )
    app = Starlette(routes=build_routes(ctx, "/auth"))
    app.state.jar = {"sid": session_id}
    app.add_middleware(_SessionInjector, jar=app.state.jar)
    return app


def test_login_redirects_and_stores_state() -> None:
    store = _MemStore()
    provider = _FakeProvider()
    app = _build_app(provider=provider, store=store, channel=MemoryAuthChannel())
    client = TestClient(app, follow_redirects=False)

    resp = client.get("/auth/fake/login?next=/dashboard")
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("https://idp.example/authorize")

    # State + nonce stored keyed by the state token.
    data = store._data["sid-1"]
    pending = data[STATE_KEY]
    state_token = provider.authorize_calls[0]["state"]
    saved = pending[state_token]
    assert saved["provider"] == "fake"
    assert saved["nonce"] == provider.authorize_calls[0]["nonce"]
    assert saved["redirect_uri"].endswith("/auth/fake/callback")
    assert saved["next"] == "/dashboard"
    # PKCE: the IdP sees the challenge; the verifier stays in the session.
    assert provider.authorize_calls[0]["code_challenge"] == pkce_challenge(
        saved["code_verifier"]
    )


def test_login_ignores_offsite_next() -> None:
    store = _MemStore()
    provider = _FakeProvider()
    app = _build_app(provider=provider, store=store, channel=MemoryAuthChannel())
    client = TestClient(app, follow_redirects=False)
    for bad in ("https://evil.example", "//evil.example", "/\\evil.example"):
        client.get("/auth/fake/login", params={"next": bad})
        state = provider.authorize_calls[-1]["state"]
        assert store._data["sid-1"][STATE_KEY][state]["next"] == "/home"


def test_redirect_uri_uses_base_url() -> None:
    store = _MemStore()
    provider = _FakeProvider()
    ctx = _RouteContext(
        providers={provider.name: provider},
        session_store=store,
        session_ttl=1800,
        auth_channel=MemoryAuthChannel(),
        default_next="/",
        on_login=None,
        on_logout=None,
        base_url="https://app.example/",
    )
    app = Starlette(routes=build_routes(ctx, "/auth"))
    app.state.jar = {"sid": "sid-1"}
    app.add_middleware(_SessionInjector, jar=app.state.jar)
    TestClient(app, follow_redirects=False).get(
        "/auth/fake/login", headers={"host": "evil.example"}
    )
    assert (
        provider.authorize_calls[0]["redirect_uri"]
        == "https://app.example/auth/fake/callback"
    )


def test_login_unknown_provider_404() -> None:
    store = _MemStore()
    app = _build_app(provider=_FakeProvider(), store=store, channel=MemoryAuthChannel())
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/auth/other/login")
    assert resp.status_code == 404


def test_callback_rejects_missing_code() -> None:
    app = _build_app(
        provider=_FakeProvider(), store=_MemStore(), channel=MemoryAuthChannel()
    )
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/auth/fake/callback?state=x")
    assert resp.status_code == 400
    assert "code" in resp.text.lower()


def test_callback_rejects_missing_session() -> None:
    app = _build_app(
        provider=_FakeProvider(),
        store=_MemStore(),
        channel=MemoryAuthChannel(),
        session_id=None,
    )
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/auth/fake/callback?code=c&state=s")
    assert resp.status_code == 400


def test_callback_rejects_mismatched_state() -> None:
    store = _MemStore()
    store._data["sid-1"] = {
        STATE_KEY: {
            "correct": {
                "nonce": "n",
                "provider": "fake",
                "redirect_uri": "http://x/auth/fake/callback",
                "next": "/home",
            }
        }
    }
    app = _build_app(provider=_FakeProvider(), store=store, channel=MemoryAuthChannel())
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/auth/fake/callback?code=c&state=WRONG")
    assert resp.status_code == 400


def test_callback_happy_path_writes_principal_and_redirects_next() -> None:
    store = _MemStore()
    store._data["sid-1"] = {
        STATE_KEY: {
            "s": {
                "nonce": "n",
                "provider": "fake",
                "redirect_uri": "http://x/auth/fake/callback",
                "next": "/dashboard",
            }
        },
    }
    provider = _FakeProvider(token_data={"access_token": "at", "refresh_token": "rt"})
    app = _build_app(provider=provider, store=store, channel=MemoryAuthChannel())
    client = TestClient(app, follow_redirects=False)

    resp = client.get("/auth/fake/callback?code=abc&state=s")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/dashboard"

    # Signing in moved the session to a new id (no session fixation).
    assert app.state.jar["sid"] != "sid-1"
    assert "sid-1" not in store._data
    # Principal written to session, state cleared, refresh_token persisted.
    data = _session(app, store)
    assert STATE_KEY not in data
    assert data["_refresh_token"] == "rt"
    assert data["auth"]["user_id"] == "fake:1"
    assert provider.exchange_calls[0] == {
        "code": "abc",
        "redirect_uri": "http://x/auth/fake/callback",
        "state": "s",
        "nonce": "n",
        "code_verifier": "",
    }


def test_callback_provider_exception_returns_400() -> None:
    store = _MemStore()
    store._data["sid-1"] = {
        STATE_KEY: {
            "s": {
                "nonce": "n",
                "provider": "fake",
                "redirect_uri": "http://x/auth/fake/callback",
                "next": "/home",
            }
        }
    }
    app = _build_app(
        provider=_FakeProvider(raises=True),
        store=store,
        channel=MemoryAuthChannel(),
    )
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/auth/fake/callback?code=abc&state=s")
    assert resp.status_code == 400


def test_logout_clears_session_and_fires_revoke() -> None:
    store = _MemStore()
    principal = ClaimsPrincipal(
        is_authenticated=True, name="A", user_id="fake:1", claims=[]
    )
    # Pre-populate session with an authenticated principal.
    store._data["sid-1"] = {
        "auth": {
            "is_authenticated": True,
            "name": "A",
            "user_id": "fake:1",
            "claims": [],
            "raw": {},
        },
        "_refresh_token": "rt",
    }
    channel = MemoryAuthChannel()
    revoked: List[str] = []

    async def fake_revoke(user_id: str) -> None:
        revoked.append(user_id)

    channel.revoke = fake_revoke  # type: ignore[assignment]

    app = _build_app(
        provider=_FakeProvider(principal=principal),
        store=store,
        channel=channel,
    )
    client = TestClient(app, follow_redirects=False)

    resp = client.post("/auth/logout")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/home"

    assert app.state.jar["sid"] != "sid-1"
    data = _session(app, store)
    assert "auth" not in data
    assert "_refresh_token" not in data
    assert revoked == ["fake:1"]


def test_logout_anonymous_does_not_revoke() -> None:
    store = _MemStore()
    store._data["sid-1"] = {}  # no auth key
    channel = MemoryAuthChannel()
    revoked: List[str] = []

    async def fake_revoke(user_id: str) -> None:
        revoked.append(user_id)

    channel.revoke = fake_revoke  # type: ignore[assignment]

    app = _build_app(provider=_FakeProvider(), store=store, channel=channel)
    client = TestClient(app, follow_redirects=False)
    resp = client.post("/auth/logout")
    assert resp.status_code == 303
    assert revoked == []


def test_logout_next_from_query() -> None:
    store = _MemStore()
    app = _build_app(provider=_FakeProvider(), store=store, channel=MemoryAuthChannel())
    client = TestClient(app, follow_redirects=False)
    resp = client.post("/auth/logout?next=/goodbye")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/goodbye"


def test_logout_refuses_offsite_next() -> None:
    store = _MemStore()
    app = _build_app(provider=_FakeProvider(), store=store, channel=MemoryAuthChannel())
    client = TestClient(app, follow_redirects=False)
    for bad in ("https://evil.example", "//evil.example", "/\\evil.example"):
        resp = client.post("/auth/logout", params={"next": bad})
        assert resp.headers["location"] == "/home"


def test_logout_is_post_only_and_same_site() -> None:
    store = _MemStore()
    app = _build_app(provider=_FakeProvider(), store=store, channel=MemoryAuthChannel())
    client = TestClient(app, follow_redirects=False)
    assert client.get("/auth/logout").status_code == 405
    resp = client.post("/auth/logout", headers={"sec-fetch-site": "cross-site"})
    assert resp.status_code == 403
    resp = client.post("/auth/logout", headers={"origin": "https://evil.example"})
    assert resp.status_code == 403
    resp = client.post("/auth/logout", headers={"origin": "http://testserver"})
    assert resp.status_code == 303


def test_concurrent_logins_each_callback_ok() -> None:
    """Two /login hits before either callback → both flows survive.

    Regression for "id_token nonce mismatch": rapid double-click on a
    provider login button used to clobber a single state/nonce slot;
    the first-flow's callback would then run against the second-flow's
    nonce and explode in ``_verify_id_token``.
    """
    store = _MemStore()
    provider = _FakeProvider()
    app = _build_app(provider=provider, store=store, channel=MemoryAuthChannel())
    client = TestClient(app, follow_redirects=False)

    client.get("/auth/fake/login?next=/one")
    first_state = provider.authorize_calls[-1]["state"]
    first_nonce = provider.authorize_calls[-1]["nonce"]

    client.get("/auth/fake/login?next=/two")
    second_state = provider.authorize_calls[-1]["state"]
    second_nonce = provider.authorize_calls[-1]["nonce"]

    assert first_state != second_state
    assert first_nonce != second_nonce

    # Complete the first flow — server should use the first flow's nonce.
    resp = client.get(f"/auth/fake/callback?code=c1&state={first_state}")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/one"
    assert provider.exchange_calls[-1]["nonce"] == first_nonce

    # Second flow's pending state still reachable.
    pending = _session(app, store)[STATE_KEY]
    assert second_state in pending
    resp = client.get(f"/auth/fake/callback?code=c2&state={second_state}")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/two"
    assert provider.exchange_calls[-1]["nonce"] == second_nonce


def test_oidc_callback_upserts_user_and_merges_stored_claims() -> None:
    """First OIDC login creates a store row; second merges stored claims."""
    import asyncio as _asyncio

    from pywire.auth import Claim, ClaimsPrincipal
    from pywire_auth import MemoryAuthStore
    from starlette.applications import Starlette

    store = MemoryAuthStore()
    session_store = _MemStore()
    provider = _FakeProvider(
        principal=ClaimsPrincipal(
            is_authenticated=True,
            name="Alice",
            user_id="fake:google-sub-123",
            claims=[
                Claim(type="sub", value="google-sub-123"),
                Claim(type="email", value="a@b.c"),
                Claim(type="name", value="Alice"),
            ],
        )
    )
    channel = MemoryAuthChannel()
    ctx = _RouteContext(
        providers={provider.name: provider},
        session_store=session_store,
        session_ttl=1800,
        auth_channel=channel,
        default_next="/",
        on_login=None,
        on_logout=None,
    )
    app = Starlette(routes=build_routes(ctx, "/auth"))
    app.state.auth_store = store
    app.state.jar = {"sid": "sid-1"}
    app.add_middleware(_SessionInjector, jar=app.state.jar)
    client = TestClient(app, follow_redirects=False)

    # First login — user row created.
    session_store._data["sid-1"] = {
        STATE_KEY: {
            "s1": {
                "nonce": "n",
                "provider": "fake",
                "redirect_uri": "http://x/auth/fake/callback",
                "next": "/",
            }
        }
    }
    resp = client.get("/auth/fake/callback?code=c&state=s1")
    assert resp.status_code == 303

    record = _asyncio.new_event_loop().run_until_complete(
        store.find_by_provider("fake", "google-sub-123")
    )
    assert record is not None
    assert record["email"] == "a@b.c"
    assert record["claims"].get("email") == "a@b.c"
    # The row has its own id; the principal carries it, not the IdP subject.
    user_id = record["user_id"]
    assert user_id != "google-sub-123"
    assert _session(app, session_store)["auth"]["user_id"] == f"fake:{user_id}"

    # Simulate a grant — app wrote role=admin to the store.
    _asyncio.new_event_loop().run_until_complete(
        store.update_user(user_id, claims={"email": "a@b.c", "role": "admin"})
    )

    # Second login — principal should be rebuilt with merged claims.
    _session(app, session_store)[STATE_KEY] = {
        "s2": {
            "nonce": "n",
            "provider": "fake",
            "redirect_uri": "http://x/auth/fake/callback",
            "next": "/",
        }
    }
    resp = client.get("/auth/fake/callback?code=c&state=s2")
    assert resp.status_code == 303
    # Session should now carry the merged admin claim.
    session_claims = dict(_session(app, session_store)["auth"]["claims"])
    assert session_claims.get("role") == "admin"
    assert session_claims.get("email") == "a@b.c"


def test_login_state_is_random() -> None:
    """Each /login produces a fresh state/nonce pair."""
    store = _MemStore()
    provider = _FakeProvider()
    app = _build_app(provider=provider, store=store, channel=MemoryAuthChannel())
    client = TestClient(app, follow_redirects=False)

    client.get("/auth/fake/login")
    first = dict(provider.authorize_calls[-1])
    client.get("/auth/fake/login")
    second = dict(provider.authorize_calls[-1])
    assert first["state"] != second["state"]
    assert first["nonce"] != second["nonce"]


def test_authorize_url_state_matches_session() -> None:
    store = _MemStore()
    provider = _FakeProvider()
    app = _build_app(provider=provider, store=store, channel=MemoryAuthChannel())
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/auth/fake/login")
    parsed = urlparse(resp.headers["location"])
    qs = parse_qs(parsed.query)
    pending = store._data["sid-1"][STATE_KEY]
    assert qs["state"][0] in pending


@pytest.mark.asyncio
async def test_same_subject_at_two_providers_is_two_users() -> None:
    from pywire_auth import MemoryAuthStore
    from pywire_auth.routes import _upsert_oidc_user

    store = MemoryAuthStore()
    request: Any = type("_Req", (), {})()
    request.app = Starlette()
    request.app.state.auth_store = store

    def who(provider: str) -> ClaimsPrincipal:
        return ClaimsPrincipal(
            is_authenticated=True,
            name=provider,
            user_id=f"{provider}:123",
            claims=[Claim(type="sub", value="123")],
        )

    google = await _upsert_oidc_user(request, "google", who("google"))
    github = await _upsert_oidc_user(request, "github", who("github"))
    assert google.user_id != github.user_id
    assert len(store._users) == 2
    again = await _upsert_oidc_user(request, "google", who("google"))
    assert again.user_id == google.user_id
