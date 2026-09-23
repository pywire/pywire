"""pywire-observability — request-ID propagation, JSON logging, OTel and Sentry recipes.

Public API:

- :func:`connect_observability` — single integration entry point.
- :class:`RequestIDMiddleware` — pure-ASGI middleware that reads inbound
  trace headers, generates a fresh ID when absent, and propagates it
  via ContextVars and ``scope["pywire_request_id"]``.
- :class:`JSONFormatter` / :func:`configure_json_logging` — JSON log
  formatter with auto-injected request/connection/event IDs.
- :mod:`pywire_observability.otel` — small helper that calls
  ``StarletteInstrumentor.instrument_app`` for users who don't want to
  learn the underlying API.
- :mod:`pywire_observability.sentry` — recipe helper for wiring
  ``sentry-sdk`` into PyWire's logging + ``@error`` hooks.
"""

from importlib.metadata import PackageNotFoundError, version

from pywire_observability import _compat as _compat  # noqa: F401  (runs floor check)
from pywire_observability.integration import connect_observability
from pywire_observability.logging import JSONFormatter, configure_json_logging
from pywire_observability.middleware import RequestIDMiddleware

try:
    __version__ = version("pywire-observability")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0+unknown"

__all__ = [
    "JSONFormatter",
    "RequestIDMiddleware",
    "__version__",
    "configure_json_logging",
    "connect_observability",
]
