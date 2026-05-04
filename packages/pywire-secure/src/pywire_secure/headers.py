"""Security response headers and a fluent CSP builder.

:class:`SecurityHeadersMiddleware` appends a fixed set of security
headers to every HTTP response. The defaults are conservative and aim
for "no breakage" on a generic PyWire app:

- ``X-Content-Type-Options: nosniff``
- ``X-Frame-Options: SAMEORIGIN``
- ``Referrer-Policy: strict-origin-when-cross-origin``
- ``Permissions-Policy: camera=(), microphone=(), geolocation=()``

HSTS and CSP are off by default — they break things when misconfigured
and need explicit opt-in. :class:`CSPBuilder` provides a chainable API
for constructing CSP header values.

Existing response headers are not overwritten; the middleware only
appends. Callers that want to override (e.g. ``X-Frame-Options: DENY``)
do so by passing the value at construction time.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional, Sequence

_DEFAULT_X_CONTENT_TYPE_OPTIONS = "nosniff"
_DEFAULT_X_FRAME_OPTIONS = "SAMEORIGIN"
_DEFAULT_REFERRER_POLICY = "strict-origin-when-cross-origin"
_DEFAULT_PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=()"


class SecurityHeadersMiddleware:
    """Append security headers to every HTTP response.

    Pass ``None`` for any default to suppress that header entirely.
    """

    def __init__(
        self,
        app: Any,
        *,
        x_content_type_options: Optional[str] = _DEFAULT_X_CONTENT_TYPE_OPTIONS,
        x_frame_options: Optional[str] = _DEFAULT_X_FRAME_OPTIONS,
        referrer_policy: Optional[str] = _DEFAULT_REFERRER_POLICY,
        permissions_policy: Optional[str] = _DEFAULT_PERMISSIONS_POLICY,
        hsts: Optional[str] = None,
        csp: Optional[str] = None,
        extra: Optional[Sequence[tuple[str, str]]] = None,
    ) -> None:
        self.app = app
        self._headers: list[tuple[bytes, bytes]] = []
        self._add("x-content-type-options", x_content_type_options)
        self._add("x-frame-options", x_frame_options)
        self._add("referrer-policy", referrer_policy)
        self._add("permissions-policy", permissions_policy)
        self._add("strict-transport-security", hsts)
        self._add("content-security-policy", csp)
        for name, value in extra or ():
            self._add(name, value)

    def _add(self, name: str, value: Optional[str]) -> None:
        if value is None:
            return
        self._headers.append((name.lower().encode("latin-1"), value.encode("latin-1")))

    async def __call__(
        self,
        scope: dict,
        receive: Callable[[], Awaitable[dict]],
        send: Callable[[dict], Awaitable[None]],
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def patched_send(message: dict) -> None:
            if message["type"] == "http.response.start":
                hdrs = list(message.get("headers", []))
                existing = {n.lower() for n, _ in hdrs}
                for name, value in self._headers:
                    if name not in existing:
                        hdrs.append((name, value))
                message = {**message, "headers": hdrs}
            await send(message)

        await self.app(scope, receive, patched_send)


class CSPBuilder:
    """Chainable Content-Security-Policy builder.

    Each directive accepts a variable number of source expressions; the
    builder accumulates them and emits a CSP-formatted string from
    :meth:`build`. Calling the same directive twice merges sources::

        csp = (
            CSPBuilder()
            .default_src("'self'")
            .script_src("'self'", "https://cdn.example.com")
            .style_src("'self'", "'unsafe-inline'")
            .build()
        )
    """

    def __init__(self) -> None:
        self._directives: dict[str, list[str]] = {}
        self._flags: list[str] = []

    def default_src(self, *sources: str) -> "CSPBuilder":
        return self._merge("default-src", sources)

    def script_src(self, *sources: str) -> "CSPBuilder":
        return self._merge("script-src", sources)

    def style_src(self, *sources: str) -> "CSPBuilder":
        return self._merge("style-src", sources)

    def img_src(self, *sources: str) -> "CSPBuilder":
        return self._merge("img-src", sources)

    def connect_src(self, *sources: str) -> "CSPBuilder":
        return self._merge("connect-src", sources)

    def font_src(self, *sources: str) -> "CSPBuilder":
        return self._merge("font-src", sources)

    def frame_src(self, *sources: str) -> "CSPBuilder":
        return self._merge("frame-src", sources)

    def frame_ancestors(self, *sources: str) -> "CSPBuilder":
        return self._merge("frame-ancestors", sources)

    def object_src(self, *sources: str) -> "CSPBuilder":
        return self._merge("object-src", sources)

    def base_uri(self, *sources: str) -> "CSPBuilder":
        return self._merge("base-uri", sources)

    def form_action(self, *sources: str) -> "CSPBuilder":
        return self._merge("form-action", sources)

    def report_uri(self, uri: str) -> "CSPBuilder":
        return self._merge("report-uri", (uri,))

    def directive(self, name: str, *sources: str) -> "CSPBuilder":
        """Add an arbitrary directive — escape hatch for CSP additions
        that don't yet have a dedicated method here."""
        return self._merge(name, sources)

    def upgrade_insecure_requests(self) -> "CSPBuilder":
        if "upgrade-insecure-requests" not in self._flags:
            self._flags.append("upgrade-insecure-requests")
        return self

    def block_all_mixed_content(self) -> "CSPBuilder":
        if "block-all-mixed-content" not in self._flags:
            self._flags.append("block-all-mixed-content")
        return self

    def build(self) -> str:
        parts: list[str] = []
        for name, sources in self._directives.items():
            parts.append(f"{name} {' '.join(sources)}")
        parts.extend(self._flags)
        return "; ".join(parts)

    def _merge(self, name: str, sources: Sequence[str]) -> "CSPBuilder":
        bucket = self._directives.setdefault(name, [])
        for src in sources:
            if src not in bucket:
                bucket.append(src)
        return self
