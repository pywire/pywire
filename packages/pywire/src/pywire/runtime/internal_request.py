"""Internal ASGI request dispatcher for middleware parity.

When a WebSocket handler needs to perform SPA navigation, it dispatches
an internal HTTP request through the full ASGI middleware stack rather
than directly instantiating a page. This ensures auth, rate limiting,
CORS, and other middleware apply uniformly to both HTTP requests and
WebSocket-initiated navigations.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import urlparse


@dataclass
class InternalResponse:
    """Captured response from an internal ASGI dispatch."""

    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    raw_headers: list[tuple[bytes, bytes]] = field(default_factory=list)
    body: bytes = b""


async def dispatch_internal(
    app: Any,
    *,
    method: str = "GET",
    path: str,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
    base_scope: dict[str, Any] | None = None,
) -> InternalResponse:
    """Dispatch an internal HTTP request through the full ASGI stack.

    Args:
        app: The ASGI application to dispatch through.
        method: HTTP method (default GET).
        path: URL path, optionally including query string.
        headers: HTTP headers as a string dict (keys lowercased).
        body: Request body bytes.
        base_scope: Optional base ASGI scope to extend (e.g. from a
            WebSocket connection). Provides defaults for server, scheme,
            client, etc.

    Returns:
        InternalResponse with captured status, headers, and body.
    """
    headers = headers or {}

    # Parse path and query string
    parsed = urlparse(path)
    pathname = parsed.path
    query_string = parsed.query.encode("ascii") if parsed.query else b""

    # Build ASGI scope
    scope: dict[str, Any] = {}
    if base_scope:
        # Copy relevant fields from base scope (e.g. WebSocket handshake)
        for key in ("server", "scheme", "root_path", "client", "state", "app"):
            if key in base_scope:
                scope[key] = base_scope[key]

    # Build headers as ASGI byte tuples
    header_list: list[tuple[bytes, bytes]] = [
        (k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()
    ]

    scope.update(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "path": pathname,
            "raw_path": pathname.encode("ascii"),
            "query_string": query_string,
            "headers": header_list,
            "_pywire_internal": True,
        }
    )
    scope.setdefault("server", ("localhost", 443))
    scope.setdefault("scheme", "https")
    scope.setdefault("root_path", "")
    scope.setdefault("client", ("127.0.0.1", 0))

    # Build receive callable — yields the request body once
    body_sent = False

    async def receive() -> dict[str, Any]:
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        # After body is sent, wait indefinitely (shouldn't be called again)
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    # Build send callable — captures response
    response = InternalResponse()
    body_chunks: list[bytes] = []

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            response.status = message["status"]
            raw = message.get("headers", [])
            response.raw_headers = [(k, v) for k, v in raw]
            response.headers = {
                k.decode("latin-1").lower(): v.decode("latin-1") for k, v in raw
            }
        elif message["type"] == "http.response.body":
            chunk = message.get("body", b"")
            if chunk:
                body_chunks.append(chunk)

    await app(scope, receive, send)
    response.body = b"".join(body_chunks)
    return response


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------


def parse_cookie_header(raw: str) -> dict[str, str]:
    """Parse a ``Cookie`` header value into a dict.

    ``Cookie: k1=v1; k2=v2`` → ``{"k1": "v1", "k2": "v2"}``
    """
    cookie: SimpleCookie = SimpleCookie()
    cookie.load(raw)
    return {k: morsel.value for k, morsel in cookie.items()}


def encode_cookie_header(cookies: dict[str, str]) -> str:
    """Encode a dict into a ``Cookie`` header value.

    ``{"k1": "v1", "k2": "v2"}`` → ``"k1=v1; k2=v2"``
    """
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def get_set_cookie_headers(
    raw_headers: list[tuple[bytes, bytes]],
) -> list[tuple[bytes, bytes]]:
    """Extract all ``Set-Cookie`` headers from raw ASGI headers."""
    return [
        (name, value) for name, value in raw_headers if name.lower() == b"set-cookie"
    ]


def parse_set_cookie_value(raw: str) -> dict[str, Any]:
    """Parse a single ``Set-Cookie`` header value into a structured dict.

    Returns dict with keys: key, value, path, domain, max_age, expires,
    secure, httponly, samesite.
    """
    cookie: SimpleCookie = SimpleCookie()
    cookie.load(raw)

    for key, morsel in cookie.items():
        result: dict[str, Any] = {
            "key": key,
            "value": morsel.value,
        }
        if morsel["path"]:
            result["path"] = morsel["path"]
        if morsel["domain"]:
            result["domain"] = morsel["domain"]
        if morsel["max-age"]:
            result["max_age"] = int(morsel["max-age"])
        if morsel["expires"]:
            result["expires"] = morsel["expires"]
        if morsel["secure"]:
            result["secure"] = True
        if morsel["httponly"]:
            result["httponly"] = True
        if morsel["samesite"]:
            result["samesite"] = morsel["samesite"]
        return result

    return {}
