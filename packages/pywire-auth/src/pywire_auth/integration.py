"""Single integration entry point — ``connect_auth(app, ...)``.

Mounts login/callback/logout routes, installs ``AuthMiddleware``, and
wires ``PolicyEngine`` + ``AuthChannel`` onto the app. Apps that only
use external OIDC providers need nothing more.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Iterable, Optional

from pywire.auth import (
    ClaimsPrincipal,
    MemoryAuthChannel,
    PolicyEngine,
)
from starlette.requests import Request

from pywire_auth.middleware import AuthMiddleware
from pywire_auth.routes import _RouteContext, build_routes


def connect_auth(
    app: Any,
    *,
    providers: Iterable[Any] = (),
    policy_engine: Optional[PolicyEngine] = None,
    auth_channel: Optional[Any] = None,
    prefix: str = "/auth",
    default_next: str = "/",
    session_ttl: Optional[int] = None,
    secret_key: Optional[str] = None,
    on_login: Optional[Callable[[ClaimsPrincipal, Request], Awaitable[None]]] = None,
    on_logout: Optional[Callable[[ClaimsPrincipal, Request], Awaitable[None]]] = None,
) -> Any:
    """Attach auth routes + middleware to a PyWire app.

    Returns the ``PolicyEngine`` so policies can be registered directly:

        engine = connect_auth(app, providers=[GoogleProvider(...)])
        engine.add_policy("AdminOnly", requires_claim=("role", "admin"))
    """
    engine = policy_engine or PolicyEngine()
    channel = auth_channel or MemoryAuthChannel()

    providers_by_name = {p.name: p for p in providers}

    ctx = _RouteContext(
        providers=providers_by_name,
        session_store=app.session_store,
        session_ttl=session_ttl or getattr(app, "session_ttl", 1800),
        auth_channel=channel,
        default_next=default_next,
        on_login=on_login,
        on_logout=on_logout,
    )

    for route in build_routes(ctx, prefix):
        app.app.router.routes.insert(0, route)

    effective_secret = (
        secret_key
        or getattr(app, "_session_secret", None)
        or _resolve_secret(app)
    )
    if not effective_secret:
        raise RuntimeError(
            "connect_auth requires secret_key (or PYWIRE_SESSION_SECRET "
            "set on the app) for session cookie verification"
        )

    app.add_middleware(
        AuthMiddleware,
        session_store=app.session_store,
        secret_key=effective_secret,
        policy_engine=engine,
        auth_channel=channel,
    )

    app._auth_engine = engine
    app._auth_channel = channel
    app._auth_providers = providers_by_name

    return engine


def _resolve_secret(app: Any) -> Optional[str]:
    from pywire.config import env

    return env("PYWIRE_SESSION_SECRET")
