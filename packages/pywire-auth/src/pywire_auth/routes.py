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

from dataclasses import replace

from pywire.auth import (
    ANONYMOUS,
    Claim,
    ClaimsPrincipal,
    clear_principal_from_session,
    write_principal_to_session,
)

logger = logging.getLogger(__name__)

STATE_KEY = "_oauth_state"
NEXT_KEY = "_oauth_next"
# Max pending OAuth flows per session. Rapid double-clicks on a login
# link used to clobber a single-slot state/nonce pair and blow up the
# callback with an "id_token nonce mismatch". Keyed-by-state storage
# keeps each flow independent; the cap prevents unbounded growth if a
# client triggers authorize_url over and over without completing.
_MAX_PENDING_STATES = 5


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
            pending = data.get(STATE_KEY)
            # Backwards-compat: older single-slot layout was a flat dict
            # without the state token as the key. Migrate by discarding.
            if not isinstance(pending, dict) or "state" in pending:
                pending = {}
            pending[state] = {
                "nonce": nonce,
                "provider": request.path_params["provider"],
                "redirect_uri": redirect_uri,
                "next": next_url,
            }
            # Cap: keep the N most recently added entries (dict insertion
            # order preserves recency).
            if len(pending) > _MAX_PENDING_STATES:
                for stale_key in list(pending)[:-_MAX_PENDING_STATES]:
                    pending.pop(stale_key, None)
            data[STATE_KEY] = pending
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

        pending = data.get(STATE_KEY) or {}
        saved = pending.get(returned_state) if isinstance(pending, dict) else None
        if not saved or saved.get("provider") != provider_name:
            return Response("Invalid OAuth state", status_code=400)

        redirect_uri = saved["redirect_uri"]
        nonce = saved["nonce"]
        next_url = saved.get("next") or ctx.default_next

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

        # Upsert the user into the auth_store (if one is installed) and
        # merge any app-managed claims (role=admin, tier=beta, etc.) back
        # onto the principal so they survive logout/login.
        principal = await _upsert_oidc_user(request, provider_name, principal)

        # Persist principal; consume this pending state (leave any other
        # concurrent flows alone).
        pending.pop(returned_state, None)
        if pending:
            data[STATE_KEY] = pending
        else:
            data.pop(STATE_KEY, None)
        data.pop(NEXT_KEY, None)  # legacy key cleanup
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


async def _upsert_oidc_user(
    request: Request, provider_name: str, principal: ClaimsPrincipal
) -> ClaimsPrincipal:
    """Ensure the OIDC-logged-in user exists in the app's auth_store.

    First login: insert a new row keyed on the provider's subject, with
    the provider's claim map. Subsequent logins: look up the row, merge
    the stored claims (app-added grants like ``role=admin``) on top of
    the provider-fresh claims (email, name, picture) and rebuild the
    principal with the combined set.

    No-op when the app has no auth_store (OIDC-only deployments that
    don't persist users) or when the principal lacks a ``<provider>:<sub>``
    prefix.
    """
    store = _auth_store_from_request(request)
    if store is None or ":" not in principal.user_id:
        return principal
    subject = principal.user_id.split(":", 1)[1]
    if not subject:
        return principal

    provider_claims = {c.type: c.value for c in principal.claims if c.type != "sub"}
    email = next(
        (c.value for c in principal.claims if c.type == "email"),
        provider_claims.get("email", ""),
    )

    existing = await store.find_by_provider(provider_name, subject)

    if existing is None:
        try:
            await store.create_user(
                user_id=subject,
                email=email,
                name=principal.name,
                claims=provider_claims,
            )
        except Exception:
            logger.warning(
                "auth_store create_user failed for %s:%s",
                provider_name,
                subject,
                exc_info=True,
            )
        try:
            await store.link_provider(subject, provider_name, subject, provider_claims)
        except Exception:
            logger.warning("auth_store link_provider failed", exc_info=True)
        # First login — provider claims ARE the canonical state.
        return principal

    # Subsequent login: merge stored claims on top of provider claims
    # (stored takes precedence so app grants stick).
    stored_claims = dict(existing.get("claims") or {})
    stored_user_id = str(existing.get("user_id") or subject)
    merged = {**provider_claims, **stored_claims}

    # Refresh the provider's view of its own claims (audit trail).
    try:
        await store.link_provider(
            stored_user_id, provider_name, subject, provider_claims
        )
    except Exception:
        logger.warning("auth_store link_provider refresh failed", exc_info=True)

    rebuilt_claims: list[Claim] = [Claim(type="sub", value=stored_user_id)]
    for ctype, cvalue in merged.items():
        rebuilt_claims.append(Claim(type=str(ctype), value=str(cvalue)))

    return replace(
        principal,
        user_id=f"{provider_name}:{stored_user_id}",
        name=principal.name or str(existing.get("name") or ""),
        claims=rebuilt_claims,
    )


def _auth_store_from_request(request: Request) -> Any:
    """Resolve the auth_store connect_auth stashed on app.state."""
    app = getattr(request, "app", None)
    state = getattr(app, "state", None) if app is not None else None
    return getattr(state, "auth_store", None) if state is not None else None


async def _form_next(request: Request) -> Optional[str]:
    if request.method != "POST":
        return None
    try:
        form = await request.form()
    except Exception:
        return None
    value = form.get("next")
    return str(value) if value else None
