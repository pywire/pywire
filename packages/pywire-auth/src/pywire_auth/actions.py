"""AuthActions — one-call claim/session mutations for live auth.

Writing a new claim to a logged-in user touches three storage layers:

1. The ``AuthStore`` — permanent user row; survives logout/login.
2. The session store — per-login principal snapshot; survives reload.
3. The ``AuthChannel`` — in-memory fan-out; updates every live tab now.

App code shouldn't have to know about any of that. ``AuthActions`` bundles
all three behind a small surface. ``connect_auth`` constructs one per app
and stashes it on ``app.state.auth``; pages use it like::

    await app.state.auth.grant(self.user, self.request, "role", "admin")
    await app.state.auth.revoke_claim(self.user, self.request, "role")
    await app.state.auth.revoke_session(self.user, self.request)

Every method runs all three writes in the right order so a hard reload,
a fresh login, and every concurrent tab stay consistent.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Iterable, List, Optional

from pywire.auth import (
    Claim,
    ClaimsPrincipal,
    clear_principal_from_session,
    write_principal_to_session,
)


def _bare_user_id(principal: ClaimsPrincipal) -> str:
    """Strip the ``<provider>:`` prefix — auth stores key on the bare id."""
    if not principal.user_id:
        return ""
    return principal.user_id.split(":", 1)[-1]


def _claims_to_dict(claims: Iterable[Claim]) -> Dict[str, str]:
    """Collapse the claim list to a dict for ``AuthStore.update_user``.

    Strips ``sub`` / ``email`` because LocalIdP re-emits them from the
    user row's top-level columns on every :meth:`principal_for_user`.
    Including them in ``record['claims']`` would just cause duplicates.
    """
    return {c.type: c.value for c in claims if c.type not in ("sub", "email")}


class AuthActions:
    """Bundles AuthStore + session + channel writes for claim/session ops."""

    def __init__(self, app: Any) -> None:
        self._app = app

    # --- claim mutations ---

    async def update_claims(
        self,
        principal: ClaimsPrincipal,
        request: Any,
        claims: List[Claim],
    ) -> ClaimsPrincipal:
        """Replace the principal's claims. Writes through all three layers."""
        new_principal = replace(
            principal,
            is_authenticated=True,
            claims=list(claims),
        )

        store = self._auth_store()
        if store is not None:
            raw_uid = _bare_user_id(principal)
            if raw_uid:
                await store.update_user(raw_uid, claims=_claims_to_dict(claims))

        await self._write_session(request, new_principal)

        channel = getattr(self._app, "_auth_channel", None)
        if channel is not None and principal.user_id:
            await channel.update_principal(principal.user_id, principal=new_principal)

        return new_principal

    async def grant(
        self,
        principal: ClaimsPrincipal,
        request: Any,
        claim_type: str,
        claim_value: str,
    ) -> ClaimsPrincipal:
        """Add or overwrite a claim, keeping the rest untouched."""
        remaining = [c for c in principal.claims if c.type != claim_type]
        return await self.update_claims(
            principal,
            request,
            remaining + [Claim(type=claim_type, value=claim_value)],
        )

    async def revoke_claim(
        self,
        principal: ClaimsPrincipal,
        request: Any,
        claim_type: str,
    ) -> ClaimsPrincipal:
        """Drop every claim of the given type. No-op if none exist."""
        filtered = [c for c in principal.claims if c.type != claim_type]
        return await self.update_claims(principal, request, filtered)

    # --- session lifecycle ---

    async def revoke_session(
        self,
        principal: ClaimsPrincipal,
        request: Any,
    ) -> None:
        """Clear this session's auth + fire a channel-wide revoke.

        The WS live-auth loop translates the channel event into a
        navigate-away for each connected tab; the current tab's session
        is also cleared so a hard reload lands on the login page via
        the ``!auth`` guard.
        """
        session_store = getattr(self._app, "session_store", None)
        sid = self._session_id(request)
        if session_store is not None and sid:
            data = await session_store.get(sid) or {}
            clear_principal_from_session(data)
            data.pop("_refresh_token", None)
            await session_store.set(
                sid, data, ttl=getattr(self._app, "session_ttl", 1800)
            )

        channel = getattr(self._app, "_auth_channel", None)
        if channel is not None and principal.user_id:
            await channel.revoke(principal.user_id)

    # --- helpers ---

    def _auth_store(self) -> Any:
        state = getattr(getattr(self._app, "app", None), "state", None)
        return getattr(state, "auth_store", None) if state is not None else None

    async def _write_session(self, request: Any, principal: ClaimsPrincipal) -> None:
        session_store = getattr(self._app, "session_store", None)
        sid = self._session_id(request)
        if session_store is None or not sid:
            return
        data = await session_store.get(sid) or {}
        write_principal_to_session(data, principal)
        await session_store.set(sid, data, ttl=getattr(self._app, "session_ttl", 1800))

    @staticmethod
    def _session_id(request: Any) -> Optional[str]:
        scope = getattr(request, "scope", None)
        if scope is None:
            return None
        return scope.get("pywire_session_id")
