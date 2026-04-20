"""Single integration entry point — ``connect_auth(app, ...)``.

Mounts login/callback/logout routes (plus LocalIdP routes when
``local_idp=`` is passed), auto-installs :class:`SessionMiddleware`
when missing, installs ``AuthMiddleware``, and wires ``PolicyEngine``
+ ``AuthChannel`` onto the app. Apps that only use external OIDC
providers need nothing more.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Iterable, Optional

from pywire.auth import (
    ClaimsPrincipal,
    MemoryAuthChannel,
    PolicyEngine,
)
from starlette.requests import Request

from pywire_auth.actions import AuthActions
from pywire_auth.middleware import AuthMiddleware
from pywire_auth.routes import _RouteContext, build_routes


def connect_auth(
    app: Any,
    *,
    providers: Iterable[Any] = (),
    local_idp: Optional[Any] = None,
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

    Pass ``local_idp=LocalIdP(...)`` to mount default password/JWT
    endpoints at ``{prefix}/local/{register,login,token,verify-token,revoke}``.
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

    for route in build_routes(ctx, prefix, local_idp=local_idp):
        app.app.router.routes.insert(0, route)

    effective_secret = (
        secret_key or getattr(app, "_session_secret", None) or _resolve_secret(app)
    )
    if not effective_secret:
        raise RuntimeError(
            "connect_auth requires secret_key (or PYWIRE_SESSION_SECRET "
            "set on the app) for session cookie verification"
        )

    # Auto-install SessionMiddleware when missing — interactive-mode PyWire
    # apps skip it by default (WS owns state), but connect_auth's routes
    # and AuthMiddleware both need scope["pywire_session_id"] to exist on
    # HTTP requests.
    _ensure_session_middleware(app, effective_secret)

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
    app._auth_local_idp = local_idp

    # Also expose on the Starlette app's state so pages can access shared
    # auth state via `app.state.X` without importing main/state.
    _app_state = app.app.state
    _app_state.auth_engine = engine
    _app_state.auth_channel = channel
    _app_state.auth_providers = list(providers_by_name.keys())
    _app_state.local_idp = local_idp
    if local_idp is not None:
        _app_state.auth_store = local_idp.store
    # Single entry point for claim/session mutations — bundles
    # auth_store + session + channel writes so app code never reaches
    # into all three directly. See pywire_auth.actions.AuthActions.
    _app_state.auth = AuthActions(app)

    return engine


def _ensure_session_middleware(app: Any, secret: str) -> None:
    """Install ``SessionMiddleware`` if it isn't already on the stack."""
    from pywire.runtime.session_middleware import SessionMiddleware

    installed = getattr(app.app, "user_middleware", []) or []
    if any(getattr(mw, "cls", None) is SessionMiddleware for mw in installed):
        return

    app.add_middleware(
        SessionMiddleware,
        session_store=app.session_store,
        session_ttl=getattr(app, "session_ttl", 1800),
        secret_key=secret,
    )


def _resolve_secret(app: Any) -> Optional[str]:
    from pywire.config import env

    return env("PYWIRE_SESSION_SECRET")
