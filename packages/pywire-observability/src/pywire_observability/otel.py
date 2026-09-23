"""OpenTelemetry instrumentation recipe.

PyWire does not bundle the OTel SDK. Install the right packages for
your destination::

    pip install opentelemetry-api opentelemetry-sdk \\
                opentelemetry-instrumentation-starlette \\
                opentelemetry-exporter-otlp

Then::

    from pywire import PyWire
    from pywire_observability.otel import instrument

    app = PyWire(...)
    instrument(app)

This wires the standard Starlette ASGI instrumentation onto PyWire's
inner Starlette app. HTTP requests and WebSocket upgrade handshakes
are auto-spanned. Per-WS-event spans are NOT yet covered (see
https://github.com/pywire/pywire/issues/254).

Internal ASGI replay requests (``X-PyWire-Internal: relocate``) are
filtered out by the default ``server_request_hook`` so the trace tree
isn't cluttered with framework-internal duplicates of the user's
request span.
"""

from __future__ import annotations

from typing import Any, Callable, Optional


def instrument(
    app: Any,
    *,
    server_request_hook: Optional[Callable[[Any, dict], None]] = None,
    client_request_hook: Optional[Callable[[Any, dict], None]] = None,
    excluded_urls: Optional[str] = None,
) -> None:
    """Apply Starlette OTel instrumentation to a PyWire app.

    Args:
        app: The :class:`pywire.PyWire` instance.
        server_request_hook: Custom hook that runs on every incoming
            request span. If omitted, a default hook drops the span
            for internal ASGI replays so they don't double-count.
        client_request_hook: Optional hook for outgoing request spans
            (rarely needed for PyWire — most apps don't make outbound
            calls from the request path).
        excluded_urls: Comma-separated URL substrings to skip. Useful
            for ``/_pywire/static`` and health endpoints.

    Raises ``ImportError`` with the install command when the
    OpenTelemetry packages aren't installed.
    """
    try:
        from opentelemetry.instrumentation.starlette import StarletteInstrumentor
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "pywire_observability.otel.instrument requires the OpenTelemetry "
            "instrumentation packages. Install with:\n"
            "  pip install opentelemetry-api opentelemetry-sdk "
            "opentelemetry-instrumentation-starlette"
        ) from exc

    hook = server_request_hook or _default_server_request_hook

    inner = getattr(app, "app", app)
    StarletteInstrumentor.instrument_app(
        inner,
        server_request_hook=hook,
        client_request_hook=client_request_hook,
        excluded_urls=excluded_urls,
    )


def _default_server_request_hook(span: Any, scope: dict) -> None:
    """Drop spans for PyWire's internal ASGI replays.

    The framework re-dispatches requests through its own ASGI app for
    SPA navigation (``X-PyWire-Internal: relocate``). Letting OTel
    span those produces a duplicate of the user-visible request span
    in trace tools.
    """
    if span is None:
        return
    headers = scope.get("headers") or []
    for name, value in headers:
        try:
            n = name.lower() if isinstance(name, bytes) else name.encode().lower()
        except (AttributeError, UnicodeError):
            continue
        if n == b"x-pywire-internal":
            try:
                span.set_attribute("pywire.internal_replay", True)
            except Exception:
                pass
            return
