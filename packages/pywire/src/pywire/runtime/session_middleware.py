"""HTTP session middleware for non-interactive server mode.

When ``interactive_server_mode=False``, page state must survive across
HTTP request/response cycles. This middleware manages a session ID in a
signed httponly cookie and persists page state to the session store
between requests.

In interactive mode, session persistence is handled by the WebSocket
handler — this middleware is only auto-added for non-interactive apps.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

COOKIE_NAME = "pywire_session"
SESSION_ID_BYTES = 24  # 32 chars in urlsafe base64


def _sign_session_id(session_id: str, secret: str) -> str:
    """Produce ``session_id.signature`` for tamper detection."""
    sig = hmac.new(secret.encode(), session_id.encode(), hashlib.sha256).hexdigest()[
        :16
    ]
    return f"{session_id}.{sig}"


def _verify_session_id(signed: str, secret: str) -> Optional[str]:
    """Return the session ID if the signature is valid, else None."""
    if "." not in signed:
        return None
    session_id, sig = signed.rsplit(".", 1)
    expected = hmac.new(
        secret.encode(), session_id.encode(), hashlib.sha256
    ).hexdigest()[:16]
    if hmac.compare_digest(sig, expected):
        return session_id
    return None


class SessionMiddleware:
    """Pure-ASGI middleware for HTTP session management.

    Reads a signed session cookie, loads state from the session store,
    and makes it available via ``scope["pywire_session_id"]``. After the
    response, the page handler is responsible for persisting state (this
    middleware only manages the session ID lifecycle).
    """

    def __init__(
        self,
        app: Any,
        *,
        session_store: Any,
        session_ttl: int = 1800,
        secret_key: Optional[str] = None,
        cookie_name: str = COOKIE_NAME,
        cookie_path: str = "/",
        cookie_secure: Optional[bool] = None,
        cookie_httponly: bool = True,
        cookie_samesite: str = "lax",
    ) -> None:
        self.app = app
        self.session_store = session_store
        self.session_ttl = session_ttl
        self.secret_key = secret_key or secrets.token_hex(32)
        self.cookie_name = cookie_name
        self.cookie_path = cookie_path
        self.cookie_secure = cookie_secure
        self.cookie_httponly = cookie_httponly
        self.cookie_samesite = cookie_samesite

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract session ID from cookie
        session_id = self._get_session_id_from_scope(scope)
        is_new_session = session_id is None

        if is_new_session:
            session_id = secrets.token_urlsafe(SESSION_ID_BYTES)

        # Make session info available to the page handler
        scope["pywire_session_id"] = session_id
        scope["pywire_session_is_new"] = is_new_session

        # The cookie is (re)issued when the session is new, or when the app
        # swapped in a new id (``rotate_session``, e.g. at login) — the id
        # is read when the response starts, after the app has run.
        issued = None if is_new_session else session_id
        await self.app(scope, receive, self._wrap_send(send, scope, issued))

    def _get_session_id_from_scope(self, scope: dict) -> Optional[str]:
        """Extract and verify session ID from the Cookie header."""
        headers = scope.get("headers", [])
        for name, value in headers:
            if name == b"cookie":
                return self._extract_session_from_cookie(value.decode("latin-1"))
        return None

    def _extract_session_from_cookie(self, cookie_header: str) -> Optional[str]:
        """Parse cookie header and verify session signature."""
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith(f"{self.cookie_name}="):
                signed_value = part[len(self.cookie_name) + 1 :]
                return _verify_session_id(signed_value, self.secret_key)
        return None

    def _cookie(self, scope: dict, session_id: str) -> str:
        signed = _sign_session_id(session_id, self.secret_key)
        cookie_parts = [
            f"{self.cookie_name}={signed}",
            f"Path={self.cookie_path}",
            f"Max-Age={self.session_ttl}",
            f"SameSite={self.cookie_samesite}",
        ]
        if self.cookie_httponly:
            cookie_parts.append("HttpOnly")
        secure = self.cookie_secure
        if secure is None:
            # Auto: a session cookie served over HTTPS never travels over
            # plain HTTP. Behind a TLS-terminating proxy the scheme is only
            # right when the server trusts its forwarded headers (uvicorn
            # --proxy-headers); pass cookie_secure=True to force it.
            secure = scope.get("scheme") == "https"
        if secure:
            cookie_parts.append("Secure")
        return "; ".join(cookie_parts)

    def _wrap_send(self, send: Any, scope: dict, issued: Optional[str]) -> Any:
        """Wrap ASGI send to inject Set-Cookie when the session id changed."""

        async def wrapped_send(message: dict) -> None:
            if message["type"] == "http.response.start":
                session_id = scope.get("pywire_session_id")
                if session_id and session_id != issued:
                    headers = list(message.get("headers", []))
                    cookie = self._cookie(scope, session_id)
                    headers.append((b"set-cookie", cookie.encode("latin-1")))
                    message = {**message, "headers": headers}
            await send(message)

        return wrapped_send


async def rotate_session(
    scope: dict,
    session_store: Any,
    ttl: int,
    data: Optional[Dict[str, Any]] = None,
) -> str:
    """Move this request's session to a fresh id and return it.

    Call it whenever the session's privilege changes (login, logout): an id
    an attacker planted or saw before the change is worthless after it. The
    session's data (or ``data``, when given) moves to the new id, the old id
    is deleted, and ``SessionMiddleware`` sends the new cookie with the
    response.
    """
    old = scope.get("pywire_session_id")
    new = secrets.token_urlsafe(SESSION_ID_BYTES)
    if data is None and old:
        data = await session_store.get(old)
    await session_store.set(new, dict(data or {}), ttl=ttl)
    if old:
        await session_store.delete(old)
    scope["pywire_session_id"] = new
    return new
