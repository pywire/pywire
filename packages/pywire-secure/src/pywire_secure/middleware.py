"""Pure-ASGI CSRF enforcement middleware.

Stack position: must be installed *below* PyWire's ``SessionMiddleware``
so ``scope["pywire_session_id"]`` is populated before this middleware
runs. ``connect_secure`` enforces the ordering by calling ``add_middleware``
in the right sequence; standalone use is the caller's responsibility.

Validation flow per request:

1. Skip non-HTTP scopes (lifespan, websocket).
2. Skip safe HTTP methods (GET/HEAD/OPTIONS/TRACE).
3. Skip configured path prefixes (defaults to ``/_pywire`` so framework
   internal endpoints with their own auth tokens are not double-checked).
4. Skip pages whose class declares ``__csrf_required__ = False``.
5. Skip when the request has no session id (a new visitor with no
   cookie cannot have been forged across origins yet — failing closed
   here would block every first POST).
6. Extract the token from ``X-CSRF-Token`` header first. If absent, and
   the request body is form-encoded, buffer the body and look for the
   ``_csrf_token`` field, then replay the body downstream.
7. Verify the token via :mod:`pywire_secure.csrf`.
8. On failure render the app's ``__error__`` page with status 403, or
   fall back to a plain 403 response.

The token is also stashed on ``scope["pywire_csrf_token"]`` for safe
methods so :class:`pywire.runtime.page.BasePage` can surface it as a
page attribute on the next render.
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Optional, Sequence
from urllib.parse import parse_qs

from pywire_secure.csrf import generate_token, verify_token

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

_FORM_CT = "application/x-www-form-urlencoded"
_MULTIPART_CT = "multipart/form-data"
_HEADER_NAME = b"x-csrf-token"
_FORM_FIELD = "_csrf_token"

# Cap on bytes the middleware will buffer to look for a form-field
# token. A reasonable HTML form fits in well under this; larger requests
# (file uploads, etc.) should send the token via the X-CSRF-Token header
# so the middleware never needs to read the body.
_MAX_BODY_BUFFER = 1 * 1024 * 1024  # 1 MiB

_BUILTIN_403 = (
    b"<!doctype html><html><head><title>403 Forbidden</title></head>"
    b"<body><h1>403 Forbidden</h1>"
    b"<p>CSRF validation failed. Reload the page and try again.</p>"
    b"</body></html>"
)


class CSRFMiddleware:
    """Validate CSRF tokens on state-mutating HTTP requests."""

    def __init__(
        self,
        app: Any,
        *,
        secret_key: str,
        pywire_app: Any = None,
        token_ttl: int = 3600,
        skip_paths: Sequence[str] = ("/_pywire",),
    ) -> None:
        self.app = app
        self.secret_key = secret_key
        self.pywire_app = pywire_app
        self.token_ttl = token_ttl
        self.skip_paths = tuple(skip_paths)

    async def __call__(
        self,
        scope: dict,
        receive: Callable[[], Awaitable[dict]],
        send: Callable[[dict], Awaitable[None]],
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        path = scope.get("path", "/")
        session_id = scope.get("pywire_session_id", "") or ""

        if session_id:
            scope["pywire_csrf_token"] = generate_token(
                session_id, self.secret_key, ttl=self.token_ttl
            )

        if method in SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        if self._is_skipped(path):
            await self.app(scope, receive, send)
            return

        if self._page_opts_out(path):
            await self.app(scope, receive, send)
            return

        if not session_id:
            await self.app(scope, receive, send)
            return

        token, replay_receive = await self._extract_token(scope, receive)
        if not token or not verify_token(
            token, session_id, self.secret_key, ttl=self.token_ttl
        ):
            await self._reject(scope, replay_receive, send)
            return

        await self.app(scope, replay_receive, send)

    def _is_skipped(self, path: str) -> bool:
        return any(path.startswith(p) for p in self.skip_paths)

    def _page_opts_out(self, path: str) -> bool:
        if self.pywire_app is None:
            return False
        router = getattr(self.pywire_app, "router", None)
        if router is None:
            return False
        try:
            match = router.match(path)
        except Exception:
            return False
        if not match:
            return False
        page_class = match[0]
        return getattr(page_class, "__csrf_required__", True) is False

    async def _extract_token(
        self,
        scope: dict,
        receive: Callable[[], Awaitable[dict]],
    ) -> "tuple[Optional[str], Callable[[], Awaitable[dict]]]":
        """Return (token, possibly-replayed receive)."""

        header_token = self._header_token(scope)
        if header_token:
            return header_token, receive

        content_type = self._content_type(scope)
        ct_lower = content_type.lower()
        if _FORM_CT not in ct_lower and _MULTIPART_CT not in ct_lower:
            return None, receive

        body = b""
        more = True
        pending: Optional[dict] = None
        oversize = False
        while more:
            msg = await receive()
            if msg["type"] != "http.request":
                # Stash non-request messages (notably http.disconnect)
                # so the downstream app still observes them via replay.
                pending = msg
                break
            body += msg.get("body", b"")
            more = msg.get("more_body", False)
            if len(body) > _MAX_BODY_BUFFER:
                # Refuse to buffer more; force header-token usage for
                # large bodies. Drop the body and let the downstream
                # handler see an empty replay so it errors cleanly
                # (the request will already be 403'd by the caller).
                oversize = True
                # Drain the rest so the connection state stays sane.
                while more:
                    msg = await receive()
                    if msg["type"] != "http.request":
                        pending = msg
                        break
                    more = msg.get("more_body", False)
                break

        token = None if oversize else self._parse_body_token(body, content_type)

        replayed = False
        replay_body = b"" if oversize else body

        async def replay() -> dict:
            nonlocal replayed, pending
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": replay_body, "more_body": False}
            if pending is not None:
                msg = pending
                pending = None
                return msg
            return await receive()

        return token, replay

    def _header_token(self, scope: dict) -> Optional[str]:
        for name, value in scope.get("headers", []):
            if name.lower() == _HEADER_NAME:
                try:
                    return value.decode("latin-1") or None
                except Exception:
                    return None
        return None

    def _content_type(self, scope: dict) -> str:
        """Return the Content-Type value with original casing.

        Boundary tokens are case-sensitive in multipart bodies, so we
        cannot lowercase here — :func:`_parse_body_token` lowercases
        only for substring matching.
        """
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-type":
                try:
                    return value.decode("latin-1")
                except Exception:
                    return ""
        return ""

    def _parse_body_token(self, body: bytes, content_type: str) -> Optional[str]:
        if not body:
            return None
        ct_lower = content_type.lower()
        if _FORM_CT in ct_lower:
            try:
                parsed = parse_qs(body.decode("latin-1"), keep_blank_values=True)
            except Exception:
                return None
            values = parsed.get(_FORM_FIELD)
            return values[0] if values else None
        if _MULTIPART_CT in ct_lower:
            return _multipart_field(body, content_type, _FORM_FIELD)
        return None

    async def _reject(
        self,
        scope: dict,
        receive: Callable[[], Awaitable[dict]],
        send: Callable[[dict], Awaitable[None]],
    ) -> None:
        body = await self._render_error_page(scope, receive)
        if body is None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"text/html; charset=utf-8"),
                        (b"content-length", str(len(_BUILTIN_403)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": _BUILTIN_403})
            return

        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"text/html; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def _render_error_page(
        self,
        scope: dict,
        receive: Callable[[], Awaitable[dict]],
    ) -> Optional[bytes]:
        """Try to render the app's ``__error__`` page with code 403.

        Returns ``None`` when the app exposes no ``__error__`` route or
        rendering fails for any reason — the caller falls back to the
        built-in 403 body.
        """
        if self.pywire_app is None:
            return None
        router = getattr(self.pywire_app, "router", None)
        if router is None:
            return None
        try:
            match = router.match("/__error__")
        except Exception:
            return None
        if not match:
            return None

        try:
            from starlette.requests import Request

            page_class = match[0]
            request = Request(scope, receive=receive)
            page = page_class(request, {}, dict(request.query_params))
            page.error_code = 403
            page.error_message = "CSRF validation failed."
            page.error_trace = ""
            response = await page.render(init=True)
            return bytes(response.body)
        except Exception:
            return None


_MULTIPART_BOUNDARY_RE = re.compile(
    r"boundary=(?:\"([^\"]+)\"|([^;\s]+))", re.IGNORECASE
)


def _multipart_field(body: bytes, content_type: str, field: str) -> Optional[str]:
    """Lightweight multipart parser sufficient for finding a single text
    field. Avoids pulling in starlette's full form parser inside an ASGI
    layer that runs before the downstream handler reads the body."""
    m = _MULTIPART_BOUNDARY_RE.search(content_type)
    if not m:
        return None
    boundary = (m.group(1) or m.group(2)).encode("latin-1")
    delim = b"--" + boundary
    needle = f'name="{field}"'.encode("latin-1")
    for part in body.split(delim):
        if needle not in part:
            continue
        sep = b"\r\n\r\n"
        idx = part.find(sep)
        if idx < 0:
            continue
        value = part[idx + len(sep) :]
        if value.endswith(b"\r\n"):
            value = value[:-2]
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return None
