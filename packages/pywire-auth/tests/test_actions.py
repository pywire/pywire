"""AuthActions — changes reach the target user's store row, sessions and tabs."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import pytest

from pywire.auth import (
    ANONYMOUS,
    Claim,
    ClaimsPrincipal,
    MemoryAuthChannel,
    PolicyEngine,
    write_principal_to_session,
)

from pywire_auth import AuthActions, LocalIdP, MemoryAuthStore
from pywire_auth.middleware import AuthMiddleware
from pywire_auth.sessions import AUTH_AT_KEY, UserSessions

SECRET = "test-signing-key-0123456789abcdef"


class _SessionStore:
    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Any]] = {}

    async def get(self, sid: str) -> Optional[Dict[str, Any]]:
        return self._data.get(sid)

    async def set(self, sid: str, data: Dict[str, Any], *, ttl: int = 0) -> None:
        self._data[sid] = data


class _FakeApp:
    def __init__(self, store, session_store, channel) -> None:
        self.session_store = session_store
        self.session_ttl = 1800
        self._auth_channel = channel
        # Mirror the Starlette state namespace connect_auth populates.
        self.app = type("_App", (), {"state": type("_State", (), {})()})()
        self.app.state.auth_store = store


class _Env:
    def __init__(self) -> None:
        self.store = MemoryAuthStore()
        self.sessions = _SessionStore()
        self.channel = MemoryAuthChannel()
        self.app = _FakeApp(self.store, self.sessions, self.channel)
        user_sessions = UserSessions(self.sessions, SECRET, 1800)
        self.actions = AuthActions(self.app, user_sessions)
        self.idp = LocalIdP(store=self.store, secret=SECRET)
        self.mw = AuthMiddleware(
            None,
            session_store=self.sessions,
            secret_key=SECRET,
            policy_engine=PolicyEngine(),
            auth_channel=self.channel,
            user_sessions=user_sessions,
        )

    async def user(self, email: str, **claims: str) -> ClaimsPrincipal:
        uid = await self.idp.create_user(email=email, password="pw", claims=claims)
        principal = await self.idp.principal_for_user(uid)
        assert principal is not None
        return principal

    async def sign_in(self, sid: str, principal: ClaimsPrincipal) -> None:
        data: Dict[str, Any] = {AUTH_AT_KEY: time.time()}
        write_principal_to_session(data, principal)
        await self.sessions.set(sid, data)

    async def who(self, sid: str) -> ClaimsPrincipal:
        """The principal the middleware resolves for a request on ``sid``."""
        return await self.mw._load_principal_from_sid({}, sid)


@pytest.mark.asyncio
async def test_grant_reaches_every_session_of_the_target_user() -> None:
    env = _Env()
    admin = await env.user("admin@b.c", role="admin")
    bob = await env.user("bob@b.c")
    await env.sign_in("admin-sid", admin)
    await env.sign_in("bob-laptop", bob)
    await env.sign_in("bob-phone", bob)

    async with env.channel.subscribe(bob.user_id) as sub:
        # An admin page grants Bob a claim: the admin's own session is untouched.
        new_bob = await env.actions.grant(bob, "role", "editor")
        event = await sub.__anext__()

    assert new_bob.has_claim("role", "editor")
    record = await env.store.get_user(bob.user_id.split(":", 1)[1])
    assert record is not None and record["claims"]["role"] == "editor"
    for sid in ("bob-laptop", "bob-phone"):
        seen = await env.who(sid)
        assert seen.user_id == bob.user_id
        assert seen.has_claim("role", "editor")
    admin_now = await env.who("admin-sid")
    assert admin_now.user_id == admin.user_id
    assert admin_now.has_claim("role", "admin")
    assert event.kind == "update" and event.principal.has_claim("role", "editor")


@pytest.mark.asyncio
async def test_revoke_claim_removes_from_store_and_sessions() -> None:
    env = _Env()
    bob = await env.user("bob@b.c", role="admin")
    await env.sign_in("bob-sid", bob)

    new_bob = await env.actions.revoke_claim(bob, "role")

    assert not new_bob.has_claim("role", "admin")
    record = await env.store.get_user(bob.user_id.split(":", 1)[1])
    assert record is not None and "role" not in record["claims"]
    assert not (await env.who("bob-sid")).has_claim("role", "admin")


@pytest.mark.asyncio
async def test_revoke_sessions_signs_the_target_out_everywhere() -> None:
    env = _Env()
    admin = await env.user("admin@b.c", role="admin")
    bob = await env.user("bob@b.c")
    await env.sign_in("admin-sid", admin)
    await env.sign_in("bob-laptop", bob)
    await env.sign_in("bob-phone", bob)
    env.sessions._data["bob-phone"]["_refresh_token"] = "rt"

    async with env.channel.subscribe(bob.user_id) as sub:
        await env.actions.revoke_sessions(bob)
        event = await sub.__anext__()

    assert event.kind == "revoke"
    assert await env.who("bob-laptop") is ANONYMOUS
    assert await env.who("bob-phone") is ANONYMOUS
    assert "auth" not in env.sessions._data["bob-phone"]
    assert "_refresh_token" not in env.sessions._data["bob-phone"]
    assert (await env.who("admin-sid")).user_id == admin.user_id

    # Signing in again afterwards works.
    await env.sign_in("bob-new", bob)
    assert (await env.who("bob-new")).user_id == bob.user_id


@pytest.mark.asyncio
async def test_update_claims_needs_a_user() -> None:
    env = _Env()
    with pytest.raises(ValueError):
        await env.actions.update_claims(ANONYMOUS, [Claim(type="role", value="x")])


@pytest.mark.asyncio
async def test_user_record_key_is_not_guessable() -> None:
    env = _Env()
    bob = await env.user("bob@b.c")
    await env.actions.revoke_sessions(bob)
    keys: List[str] = [k for k in env.sessions._data if k.startswith("pywire-auth:")]
    assert len(keys) == 1 and bob.user_id not in keys[0]
