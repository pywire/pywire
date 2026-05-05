"""Pure-ASGI request-ID propagation middleware.

For every HTTP request and WebSocket connection, the middleware:

1. Reads inbound trace headers in priority order:
   ``traceparent`` (W3C) → ``x-request-id`` → ``x-correlation-id``.
2. Generates a fresh ID when none is present (UUID4 hex by default).
3. Writes it to ``scope["pywire_request_id"]`` so :class:`BasePage`
   surfaces it as ``self.request_id`` and other middleware can read it.
4. Sets :data:`pywire.runtime.observability.request_id_ctx` for the
   duration of the request — log records emitted from anywhere in the
   request path (handlers, background tasks spawned during the request,
   render callbacks) automatically carry the id when the JSON formatter
   is active.
5. Echoes the id back as ``X-Request-ID`` on HTTP responses so clients
   and downstream services can correlate.

Generated IDs are UUID4 hex by default. When ``traceparent`` is present,
the W3C trace-id portion is preserved instead so OTel-aware backends
(Datadog, Honeycomb, Tempo, Jaeger) link logs to the originating trace
without bespoke configuration.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Awaitable, Callable, Optional, Sequence

# W3C trace-context: ``00-<32 hex trace_id>-<16 hex span_id>-<2 hex flags>``
_TRACEPARENT_RE = re.compile(r"^[0-9a-f]{2}-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$")


class RequestIDMiddleware:
    """Read or mint a request id and propagate it through the request."""

    def __init__(
        self,
        app: Any,
        *,
        header_name: str = "x-request-id",
        inbound_headers: Sequence[str] = (
            "traceparent",
            "x-request-id",
            "x-correlation-id",
        ),
        echo_response_header: bool = True,
    ) -> None:
        self.app = app
        self.header_name = header_name.lower()
        self.inbound_headers = tuple(h.lower() for h in inbound_headers)
        self.echo_response_header = echo_response_header

    async def __call__(
        self,
        scope: dict,
        receive: Callable[[], Awaitable[dict]],
        send: Callable[[dict], Awaitable[None]],
    ) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        request_id = self._extract_or_generate(scope)
        scope["pywire_request_id"] = request_id

        # Set the ContextVar before dispatching so log records emitted
        # synchronously inside the downstream handler see the id. The
        # ContextVar lives in pywire core (pure stdlib).
        from pywire.runtime.observability import request_id_ctx

        token = request_id_ctx.set(request_id)
        try:
            if scope["type"] == "http" and self.echo_response_header:
                await self.app(scope, receive, self._wrap_send(send, request_id))
            else:
                await self.app(scope, receive, send)
        finally:
            request_id_ctx.reset(token)

    def _extract_or_generate(self, scope: dict) -> str:
        for name, value in scope.get("headers", []):
            try:
                lower = name.lower()
            except AttributeError:
                continue
            if isinstance(lower, bytes):
                lower_str = lower.decode("latin-1")
            else:
                lower_str = lower
            if lower_str not in self.inbound_headers:
                continue
            decoded = self._decode_header_value(value)
            if not decoded:
                continue
            extracted = (
                _trace_id_from_traceparent(decoded)
                if lower_str == "traceparent"
                else decoded
            )
            if extracted:
                return extracted
        return uuid.uuid4().hex

    @staticmethod
    def _decode_header_value(value: Any) -> Optional[str]:
        if isinstance(value, bytes):
            try:
                return value.decode("latin-1")
            except UnicodeDecodeError:
                return None
        if isinstance(value, str):
            return value
        return None

    def _wrap_send(
        self,
        send: Callable[[dict], Awaitable[None]],
        request_id: str,
    ) -> Callable[[dict], Awaitable[None]]:
        echo_name = self.header_name.encode("latin-1")
        echo_value = request_id.encode("latin-1")

        async def patched(message: dict) -> None:
            if message["type"] == "http.response.start":
                hdrs = list(message.get("headers", []))
                if not any(
                    (n.lower() if isinstance(n, bytes) else n.encode().lower())
                    == echo_name
                    for n, _ in hdrs
                ):
                    hdrs.append((echo_name, echo_value))
                message = {**message, "headers": hdrs}
            await send(message)

        return patched


def _trace_id_from_traceparent(value: str) -> Optional[str]:
    """Pull the 32-hex trace_id from a W3C traceparent header.

    Returns ``None`` for malformed values so callers fall through to
    the next header in the priority list (or the UUID4 fallback).
    """
    match = _TRACEPARENT_RE.match(value.strip())
    if match is None:
        return None
    return match.group(1)
