"""OAuth login / callback / logout route handlers.

Routes are mounted by :func:`pywire_auth.integration.connect_auth`:

- ``GET {prefix}/{provider}/login``    → redirect to IdP authorize URL
- ``GET {prefix}/{provider}/callback`` → exchange code, persist principal
- ``POST {prefix}/logout``             → clear auth, fire channel.revoke

OAuth state + nonce live in the pywire session (signed cookie, same
session store as page state). Zero DB required for external-only flows.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any, Awaitable, Callable, Dict, Optional

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from pywire.auth import (
    ANONYMOUS,
    ClaimsPrincipal,
    clear_principal_from_session,
    write_principal_to_session,
)
from pywire.auth.session import AUTH_KEY

logger = logging.getLogger(__name__)

STATE_KEY = "_oauth_state"
NEXT_KEY = "_oauth_next"


class _RouteContext:
    """State shared across the mounted routes."""

    def __init__(
        self,
        *,
        providers: Dict[str, Any],
        session_store: Any,
        session_ttl: int,
        auth_channel: Any,
        default_next: str,
        on_login: Optional[Callable[[ClaimsPrincipal, Request], Awaitable[None]]],
        on_logout: Optional[Callable[[ClaimsPrincipal, Request], Awaitable[None]]],
    ) -> None:
        self.providers = providers
        self.session_store = session_store
        self.session_ttl = session_ttl
        self.auth_channel = auth_channel
        self.default_next = default_next
        self.on_login = on_login
        self.on_logout = on_logout


def build_routes(
    ctx: _RouteContext, prefix: str, *, local_idp: Optional[Any] = None
) -> list:
    async def login(request: Request) -> Response:
        provider = ctx.providers.get(request.path_params["provider"])
        if provider is None:
            return Response("Unknown provider", status_code=404)

        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        redirect_uri = str(
            request.url_for(
                "pywire_auth_callback", provider=request.path_params["provider"]
            )
        )
        next_url = request.query_params.get("next") or ctx.default_next

        session_id = _session_id_or_none(request)
        if session_id:
            data = await ctx.session_store.get(session_id) or {}
            data[STATE_KEY] = {
                "state": state,
                "nonce": nonce,
                "provider": request.path_params["provider"],
                "redirect_uri": redirect_uri,
            }
            data[NEXT_KEY] = next_url
            await ctx.session_store.set(session_id, data, ttl=ctx.session_ttl)

        url = await provider.authorize_url(
            redirect_uri=redirect_uri, state=state, nonce=nonce
        )
        return RedirectResponse(url, status_code=303)

    async def callback(request: Request) -> Response:
        provider_name = request.path_params["provider"]
        provider = ctx.providers.get(provider_name)
        if provider is None:
            return Response("Unknown provider", status_code=404)

        code = request.query_params.get("code")
        returned_state = request.query_params.get("state")
        if not code:
            return Response("Missing code", status_code=400)

        session_id = _session_id_or_none(request)
        if not session_id:
            return Response("No session — OAuth requires cookies", status_code=400)
        data = await ctx.session_store.get(session_id) or {}

        saved = data.get(STATE_KEY) or {}
        if (
            not saved
            or saved.get("state") != returned_state
            or saved.get("provider") != provider_name
        ):
            return Response("Invalid OAuth state", status_code=400)

        redirect_uri = saved["redirect_uri"]
        nonce = saved["nonce"]

        try:
            principal, token_data = await provider.exchange_code(
                code=code,
                redirect_uri=redirect_uri,
                state=returned_state or "",
                nonce=nonce,
            )
        except Exception as exc:
            logger.warning("OAuth exchange failed: %s", exc, exc_info=True)
            return Response("Login failed", status_code=400)

        # Persist principal; drop state + nonce.
        data.pop(STATE_KEY, None)
        next_url = data.pop(NEXT_KEY, ctx.default_next)
        write_principal_to_session(data, principal)
        if token_data.get("refresh_token"):
            data["_refresh_token"] = token_data["refresh_token"]
        await ctx.session_store.set(session_id, data, ttl=ctx.session_ttl)

        if ctx.on_login:
            try:
                await ctx.on_login(principal, request)
            except Exception:
                logger.warning("on_login callback raised", exc_info=True)

        return RedirectResponse(next_url, status_code=303)

    async def logout(request: Request) -> Response:
        session_id = _session_id_or_none(request)
        principal = ANONYMOUS
        if session_id:
            data = await ctx.session_store.get(session_id) or {}
            from pywire.auth import read_principal_from_session

            principal = read_principal_from_session(data) or ANONYMOUS
            clear_principal_from_session(data)
            data.pop("_refresh_token", None)
            await ctx.session_store.set(session_id, data, ttl=ctx.session_ttl)

        if principal.is_authenticated and principal.user_id:
            try:
                await ctx.auth_channel.revoke(principal.user_id)
            except Exception:
                logger.warning("AuthChannel.revoke failed", exc_info=True)

        if ctx.on_logout:
            try:
                await ctx.on_logout(principal, request)
            except Exception:
                logger.warning("on_logout callback raised", exc_info=True)

        next_url = (
            request.query_params.get("next")
            or (await _form_next(request))
            or ctx.default_next
        )
        return RedirectResponse(next_url, status_code=303)

    # Mount LocalIdP routes first so /auth/local/* matches before the
    # dynamic /auth/{provider}/* route (which would otherwise 404 with
    # "Unknown provider").
    local_routes: list = []
    if local_idp is not None:
        from pywire_auth.local.routes import build_local_routes

        local_routes = list(build_local_routes(ctx, prefix, local_idp))

    return [
        *local_routes,
        Route(
            f"{prefix}/{{provider}}/login",
            login,
            methods=["GET"],
            name="pywire_auth_login",
        ),
        Route(
            f"{prefix}/{{provider}}/callback",
            callback,
            methods=["GET"],
            name="pywire_auth_callback",
        ),
        Route(
            f"{prefix}/logout",
            logout,
            methods=["GET", "POST"],
            name="pywire_auth_logout",
        ),
    ]


def _session_id_or_none(request: Request) -> Optional[str]:
    # Read the session ID the same way pywire writes it.
    return request.scope.get("pywire_session_id")


async def _form_next(request: Request) -> Optional[str]:
    if request.method != "POST":
        return None
    try:
        form = await request.form()
    except Exception:
        return None
    value = form.get("next")
    return str(value) if value else None
