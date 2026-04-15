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
from typing import Any, Optional

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
        cookie_secure: bool = False,
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

        # Load existing session data into scope
        if not is_new_session:
            data = await self.session_store.get(session_id)
            scope["pywire_session_data"] = data
        else:
            scope["pywire_session_data"] = None

        # Wrap send to inject Set-Cookie header for new sessions
        if is_new_session:
            send = self._wrap_send(send, session_id)

        await self.app(scope, receive, send)

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

    def _wrap_send(self, send: Any, session_id: str) -> Any:
        """Wrap ASGI send to inject Set-Cookie on response start."""
        signed = _sign_session_id(session_id, self.secret_key)
        cookie_parts = [
            f"{self.cookie_name}={signed}",
            f"Path={self.cookie_path}",
            f"Max-Age={self.session_ttl}",
            f"SameSite={self.cookie_samesite}",
        ]
        if self.cookie_httponly:
            cookie_parts.append("HttpOnly")
        if self.cookie_secure:
            cookie_parts.append("Secure")
        cookie_value = "; ".join(cookie_parts)

        async def wrapped_send(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"set-cookie", cookie_value.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        return wrapped_send
