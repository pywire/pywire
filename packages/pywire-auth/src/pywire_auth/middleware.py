"""ASGI middleware that populates ``scope['user']`` from the pywire session.

Piggybacks on the existing ``pywire_session`` cookie produced by
``SessionMiddleware`` in interactive apps, or by the PyWire session
store elsewhere. Reads the ``auth`` key of the session payload and
deserializes a ``ClaimsPrincipal``.

If no session data is present the principal is ``ANONYMOUS`` — downstream
``get_user`` returns a valid ``ClaimsPrincipal`` instead of ``None``,
keeping guard / policy checks uniform.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

from pywire.auth import (
    ANONYMOUS,
    AuthContext,
    ClaimsPrincipal,
    read_principal_from_session,
    set_auth_context,
    reset_auth_context,
)
from pywire.auth.session import AUTH_KEY
from pywire.runtime.session_middleware import _verify_session_id

logger = logging.getLogger(__name__)


class AuthMiddleware:
    """Populate ``scope['user']`` and per-request ``AuthContext``."""

    def __init__(
        self,
        app: Any,
        *,
        session_store: Any,
        secret_key: str,
        policy_engine: Any,
        auth_channel: Any,
        cookie_name: str = "pywire_session",
    ) -> None:
        self.app = app
        self.session_store = session_store
        self.secret_key = secret_key
        self.policy_engine = policy_engine
        self.auth_channel = auth_channel
        self.cookie_name = cookie_name

    async def __call__(
        self,
        scope: dict,
        receive: Callable[[], Awaitable[dict]],
        send: Callable[[dict], Awaitable[None]],
    ) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        principal = await self._load_principal(scope)
        scope["user"] = principal

        ctx = AuthContext(
            principal=principal,
            engine=self.policy_engine,
            channel=self.auth_channel,
        )
        token = set_auth_context(ctx)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_auth_context(token)

    async def _load_principal(self, scope: dict) -> ClaimsPrincipal:
        session_id = self._extract_session_id(scope)
        if not session_id:
            return ANONYMOUS

        try:
            data = await self.session_store.get(session_id)
        except Exception:
            logger.warning("Session store read failed", exc_info=True)
            return ANONYMOUS
        if not data:
            return ANONYMOUS

        # PyWire's session payload is a single dict. Auth lives under AUTH_KEY.
        principal = read_principal_from_session(data)
        if principal is None:
            # Some apps may not use the wrapper; look for a bare principal dict
            # under the same key.
            principal = read_principal_from_session({AUTH_KEY: data.get(AUTH_KEY)})
        return principal or ANONYMOUS

    def _extract_session_id(self, scope: dict) -> Optional[str]:
        headers = scope.get("headers", [])
        for name, value in headers:
            if name == b"cookie":
                return self._parse_cookie(value.decode("latin-1"))
        return None

    def _parse_cookie(self, header: str) -> Optional[str]:
        prefix = f"{self.cookie_name}="
        for part in header.split(";"):
            part = part.strip()
            if part.startswith(prefix):
                signed = part[len(prefix) :]
                return _verify_session_id(signed, self.secret_key)
        return None
