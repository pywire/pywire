"""pywire-secure — security middleware for PyWire apps.

Public API:

- :func:`connect_secure` — single integration entry point. Installs CSRF,
  security headers, rate limiting, and HTTPS redirect middleware.
- :class:`CSRFMiddleware` — standalone ASGI CSRF enforcement, useful when
  ``connect_secure`` is too coarse.
- :class:`SecurityHeadersMiddleware` — standalone response-header injector.
- :class:`CSPBuilder` — fluent Content-Security-Policy builder.
- :func:`generate_token` / :func:`verify_token` — low-level CSRF token
  primitives, exposed for testing and custom flows.
"""

from pywire_secure import _compat as _compat  # noqa: F401  (runs floor check on import)
from pywire_secure._version import __version__
from pywire_secure.csrf import generate_token, verify_token

__all__ = [
    "__version__",
    "generate_token",
    "verify_token",
]
