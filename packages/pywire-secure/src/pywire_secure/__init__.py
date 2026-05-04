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
from pywire_secure.headers import CSPBuilder, SecurityHeadersMiddleware
from pywire_secure.integration import connect_secure
from pywire_secure.middleware import CSRFMiddleware

__all__ = [
    "CSPBuilder",
    "CSRFMiddleware",
    "SecurityHeadersMiddleware",
    "__version__",
    "connect_secure",
    "generate_token",
    "verify_token",
]
