"""AuthActions — one-call propagation across store + session + channel."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from pywire.auth import (
    Claim,
    ClaimsPrincipal,
    MemoryAuthChannel,
    read_principal_from_session,
)

from pywire_auth import AuthActions, LocalIdP, MemoryAuthStore


class _SessionStore:
    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Any]] = {}

    async def get(self, sid: str) -> Optional[Dict[str, Any]]:
        return self._data.get(sid)

    async def set(
        self, sid: str, data: Dict[str, Any], *, ttl: int = 0
    ) -> None:
        self._data[sid] = dict(data)


class _FakeApp:
    def __init__(self, store, session_store, channel) -> None:
        self.session_store = session_store
        self.session_ttl = 1800
        self._auth_channel = channel
        # Mirror the Starlette state namespace connect_auth populates.
        self.app = type("_App", (), {"state": type("_State", (), {})()})()
        self.app.state.auth_store = store


class _FakeRequest:
    def __init__(self, sid: str | None) -> None:
        self.scope: Dict[str, Any] = {}
        if sid:
            self.scope["pywire_session_id"] = sid


async def _build() -> tuple[AuthActions, _FakeApp, LocalIdP, MemoryAuthChannel]:
    store = MemoryAuthStore()
    session_store = _SessionStore()
    channel = MemoryAuthChannel()
    app = _FakeApp(store, session_store, channel)
    actions = AuthActions(app)
    idp = LocalIdP(store=store, secret="s" * 32)
    return actions, app, idp, channel


@pytest.mark.asyncio
async def test_grant_writes_all_three_layers() -> None:
    actions, app, idp, channel = await _build()
    uid = await idp.create_user(email="a@b.c", password="pw", name="Alice")
    principal = await idp.principal_for_user(uid)
    assert principal is not None

    request = _FakeRequest("sid-1")
    received: List[Any] = []

    async with channel.subscribe(principal.user_id) as sub:
        # Seed the session with the initial principal so AuthActions has
        # something to overwrite.
        await app.session_store.set(
            "sid-1",
            {"auth": {
                "is_authenticated": True,
                "user_id": principal.user_id,
                "name": principal.name,
                "claims": [(c.type, c.value) for c in principal.claims],
                "raw": {},
            }},
        )

        new_principal = await actions.grant(principal, request, "role", "admin")

        # 1. Store: user record has role claim
        record = await app.app.state.auth_store.get_user(uid)
        assert record is not None
        assert record["claims"].get("role") == "admin"

        # 2. Session: principal has role claim
        data = await app.session_store.get("sid-1")
        assert data is not None
        stored = read_principal_from_session(data)
        assert stored is not None
        assert stored.has_claim("role", "admin")

        # 3. Channel: subscriber got an update event
        event = await sub.__anext__()
        received.append(event)

    assert received[0].kind == "update"
    assert received[0].principal is not None
    assert received[0].principal.has_claim("role", "admin")
    assert new_principal.has_claim("role", "admin")


@pytest.mark.asyncio
async def test_revoke_claim_removes_from_all_layers() -> None:
    actions, app, idp, _ = await _build()
    uid = await idp.create_user(
        email="a@b.c", password="pw", claims={"role": "admin"}
    )
    principal = await idp.principal_for_user(uid)
    assert principal is not None
    assert principal.has_claim("role", "admin")

    request = _FakeRequest("sid-1")
    new_principal = await actions.revoke_claim(principal, request, "role")

    assert not new_principal.has_claim("role", "admin")
    record = await app.app.state.auth_store.get_user(uid)
    assert record is not None
    assert "role" not in (record.get("claims") or {})


@pytest.mark.asyncio
async def test_revoke_session_clears_and_fires_revoke_event() -> None:
    actions, app, idp, channel = await _build()
    uid = await idp.create_user(email="a@b.c", password="pw")
    principal = await idp.principal_for_user(uid)
    assert principal is not None

    # Seed the session.
    await app.session_store.set(
        "sid-1",
        {"auth": {
            "is_authenticated": True,
            "user_id": principal.user_id,
            "name": "",
            "claims": [],
            "raw": {},
        }, "_refresh_token": "rt"},
    )

    request = _FakeRequest("sid-1")
    received: List[Any] = []

    async with channel.subscribe(principal.user_id) as sub:
        await actions.revoke_session(principal, request)
        event = await sub.__anext__()
        received.append(event)

    # Session cleared
    data = await app.session_store.get("sid-1")
    assert data is not None
    assert "auth" not in data
    assert "_refresh_token" not in data

    # Channel emitted revoke
    assert received[0].kind == "revoke"


@pytest.mark.asyncio
async def test_update_claims_no_session_noop_ok() -> None:
    """When there's no session id on the request, store + channel still fire."""
    actions, app, idp, channel = await _build()
    uid = await idp.create_user(email="a@b.c", password="pw")
    principal = await idp.principal_for_user(uid)
    assert principal is not None

    request = _FakeRequest(None)  # no pywire_session_id
    received: List[Any] = []

    async with channel.subscribe(principal.user_id) as sub:
        await actions.update_claims(
            principal, request, [Claim(type="role", value="editor")]
        )
        event = await sub.__anext__()
        received.append(event)

    record = await app.app.state.auth_store.get_user(uid)
    assert record is not None
    assert record["claims"].get("role") == "editor"
    assert received[0].kind == "update"
