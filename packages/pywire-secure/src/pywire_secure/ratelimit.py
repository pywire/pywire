"""slowapi adapter, gated behind the ``ratelimit`` extra.

slowapi is a Starlette/FastAPI rate limiter built on the limits library.
We wrap it just enough to plug into PyWire's app shape: instantiate a
``Limiter``, expose it on ``app.app.state.limiter`` so route handlers
can apply per-route ``@limiter.limit("5/minute")`` decorators, and add
slowapi's exception handler so 429s render cleanly.

Importing this module without ``slowapi`` installed raises ``ImportError``
with a hint — callers should either install the extra or skip rate
limiting via ``connect_secure(rate_limit=False)``.
"""

from __future__ import annotations

from typing import Any, Optional


def install_rate_limit(
    app: Any,
    *,
    default_limit: str = "100/minute",
    key_func: Optional[Any] = None,
    storage_uri: Optional[str] = None,
) -> Any:
    """Configure slowapi on a PyWire app and return the ``Limiter``.

    The returned limiter is also stashed on ``app.app.state.limiter``
    so handlers reach it via ``request.app.state.limiter``.
    """
    try:
        from slowapi import Limiter, _rate_limit_exceeded_handler
        from slowapi.errors import RateLimitExceeded
        from slowapi.util import get_remote_address
    except ImportError as exc:
        raise ImportError(
            "pywire-secure[ratelimit] is required for rate limiting. "
            "Run: pip install 'pywire-secure[ratelimit]'"
        ) from exc

    limiter_kwargs: dict[str, Any] = {
        "key_func": key_func or get_remote_address,
        "default_limits": [default_limit],
    }
    if storage_uri:
        limiter_kwargs["storage_uri"] = storage_uri

    limiter = Limiter(**limiter_kwargs)
    starlette_app = getattr(app, "app", app)
    starlette_app.state.limiter = limiter
    starlette_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    return limiter
