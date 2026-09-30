"""Signing in and out, and changes that reach every session of a user.

A session holds a copy of the principal it signed in with. Changing a user's
claims or signing them out from somewhere else (an admin page, a password
change) has to reach sessions this request can't see: other browsers, other
devices. :class:`UserSessions` keeps one small record per user in the session
store saying when their claims last changed and when their sessions were last
revoked. ``AuthMiddleware`` compares each session's sign-in time with that
record and brings the session up to date, so the change lands on the user's
next request wherever they are, while live tabs hear it on the ``AuthChannel``.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import replace
from typing import Any, Dict, Iterable, Optional

from starlette.requests import Request

from pywire.auth import (
    ANONYMOUS,
    Claim,
    ClaimsPrincipal,
    clear_principal_from_session,
    read_principal_from_session,
    write_principal_to_session,
)
from pywire.runtime.session_middleware import rotate_session

# When this session signed in (or last caught up with its user's record).
AUTH_AT_KEY = "_auth_at"
REFRESH_TOKEN_KEY = "_refresh_token"


class UserSessions:
    """Per-user auth changes, applied to each of the user's sessions."""

    def __init__(self, session_store: Any, secret: str, ttl: int) -> None:
        self._store = session_store
        self._secret = secret.encode("utf-8")
        # A record outlives every session it has to reach: sessions expire
        # ``ttl`` after their last request, and a request made after the
        # change has already applied it.
        self._ttl = ttl

    def _key(self, user_id: str) -> str:
        # Keyed so nobody can name the record through an API that looks up
        # session ids.
        digest = hmac.new(self._secret, user_id.encode("utf-8"), hashlib.sha256)
        return f"pywire-auth:user:{digest.hexdigest()}"

    async def _record(self, user_id: str, **fields: Any) -> None:
        key = self._key(user_id)
        record = dict(await self._store.get(key) or {})
        record.update(fields)
        await self._store.set(key, record, ttl=self._ttl)

    async def revoke(self, user_id: str) -> None:
        """Sign ``user_id`` out of every session that signed in before now."""
        await self._record(user_id, revoked_at=time.time())

    async def set_claims(self, user_id: str, claims: Iterable[Claim]) -> None:
        """Give every current session of ``user_id`` these claims."""
        await self._record(
            user_id,
            claims_at=time.time(),
            claims=[[c.type, c.value] for c in claims],
        )

    async def reconcile(
        self,
        session_id: str,
        data: Dict[str, Any],
        principal: ClaimsPrincipal,
    ) -> ClaimsPrincipal:
        """The session's principal after applying its user's record."""
        if not principal.is_authenticated or not principal.user_id:
            return principal
        record = await self._store.get(self._key(principal.user_id))
        if not record:
            return principal
        signed_in_at = float(data.get(AUTH_AT_KEY) or 0)
        revoked_at = record.get("revoked_at")
        if revoked_at and signed_in_at < revoked_at:
            clear_session_auth(data)
            await self._store.set(session_id, data, ttl=self._ttl)
            return ANONYMOUS
        claims_at = record.get("claims_at")
        if claims_at and signed_in_at < claims_at:
            principal = replace(
                principal,
                claims=[Claim(type=t, value=v) for t, v in record.get("claims", [])],
            )
            write_principal_to_session(data, principal)
            data[AUTH_AT_KEY] = claims_at
            await self._store.set(session_id, data, ttl=self._ttl)
        return principal


def clear_session_auth(data: Dict[str, Any]) -> None:
    clear_principal_from_session(data)
    data.pop(AUTH_AT_KEY, None)
    data.pop(REFRESH_TOKEN_KEY, None)


async def sign_in(
    ctx: Any,
    request: Request,
    principal: ClaimsPrincipal,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """Put ``principal`` in this browser's session, under a new session id.

    ``data`` is the session's current contents when the caller already read
    (and changed) them. The id changes so one planted in the victim's browser
    before sign-in is worthless after it.
    """
    if data is None:
        sid = request.scope.get("pywire_session_id")
        data = (await ctx.session_store.get(sid) if sid else None) or {}
    write_principal_to_session(data, principal)
    data[AUTH_AT_KEY] = time.time()
    await rotate_session(request.scope, ctx.session_store, ctx.session_ttl, data)


async def sign_out(ctx: Any, request: Request) -> ClaimsPrincipal:
    """Remove the principal from this browser's session; return who it was."""
    sid = request.scope.get("pywire_session_id")
    data = (await ctx.session_store.get(sid) if sid else None) or {}
    principal = read_principal_from_session(data) or ANONYMOUS
    clear_session_auth(data)
    await rotate_session(request.scope, ctx.session_store, ctx.session_ttl, data)
    return principal
