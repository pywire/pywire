"""AuthActions — one-call claim/session changes for live auth.

Changing a signed-in user's claims touches three layers:

1. The ``AuthStore`` — permanent user row; survives logout/login.
2. Every session the user is signed in with, on any browser or device.
3. The ``AuthChannel`` — in-memory fan-out; updates every live tab now.

App code shouldn't have to know about any of that. ``AuthActions`` bundles
all three behind a small surface. ``connect_auth`` constructs one per app
and stashes it on ``app.state.auth``. Every method acts on the user it is
given, whoever calls it, so the same calls serve a user's own settings page
and an admin page::

    await app.state.auth.grant(user, "role", "admin")
    await app.state.auth.revoke_claim(user, "role")
    await app.state.auth.revoke_sessions(user)  # sign out everywhere
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Iterable, List

from pywire.auth import Claim, ClaimsPrincipal

from pywire_auth.sessions import UserSessions


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

    def __init__(self, app: Any, user_sessions: UserSessions) -> None:
        self._app = app
        self._sessions = user_sessions

    # --- claim mutations ---

    async def update_claims(
        self, principal: ClaimsPrincipal, claims: List[Claim]
    ) -> ClaimsPrincipal:
        """Replace ``principal``'s claims in the store and every session."""
        if not principal.user_id:
            raise ValueError("update_claims needs a signed-in user's principal")
        new_principal = replace(principal, is_authenticated=True, claims=list(claims))

        store = self._auth_store()
        if store is not None:
            await store.update_user(
                _bare_user_id(principal), claims=_claims_to_dict(claims)
            )

        await self._sessions.set_claims(principal.user_id, new_principal.claims)

        channel = getattr(self._app, "_auth_channel", None)
        if channel is not None:
            await channel.update_principal(principal.user_id, principal=new_principal)

        return new_principal

    async def grant(
        self, principal: ClaimsPrincipal, claim_type: str, claim_value: str
    ) -> ClaimsPrincipal:
        """Add or overwrite a claim, keeping the rest untouched."""
        remaining = [c for c in principal.claims if c.type != claim_type]
        return await self.update_claims(
            principal, remaining + [Claim(type=claim_type, value=claim_value)]
        )

    async def revoke_claim(
        self, principal: ClaimsPrincipal, claim_type: str
    ) -> ClaimsPrincipal:
        """Drop every claim of the given type. No-op if none exist."""
        filtered = [c for c in principal.claims if c.type != claim_type]
        return await self.update_claims(principal, filtered)

    # --- session lifecycle ---

    async def revoke_sessions(self, principal: ClaimsPrincipal) -> None:
        """Sign ``principal``'s user out of every session they have.

        Each session loses its auth on its next request; live tabs hear a
        channel revoke and navigate away now.
        """
        if not principal.user_id:
            return
        await self._sessions.revoke(principal.user_id)
        channel = getattr(self._app, "_auth_channel", None)
        if channel is not None:
            await channel.revoke(principal.user_id)

    # --- helpers ---

    def _auth_store(self) -> Any:
        state = getattr(getattr(self._app, "app", None), "state", None)
        return getattr(state, "auth_store", None) if state is not None else None
