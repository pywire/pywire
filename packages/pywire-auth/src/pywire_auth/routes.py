"""OAuth login / callback / logout route handlers.

Routes are mounted by :func:`pywire_auth.integration.connect_auth`:

- ``GET {prefix}/{provider}/login``    → redirect to IdP authorize URL
- ``GET {prefix}/{provider}/callback`` → exchange code, persist principal
- ``POST {prefix}/logout``             → clear auth, fire channel.revoke

OAuth state, nonce and PKCE verifier live in the pywire session (signed
cookie, same session store as page state). Zero DB required for
external-only flows.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from dataclasses import replace
from typing import Any, Awaitable, Callable, Dict, Optional

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from pywire.auth import Claim, ClaimsPrincipal

from pywire_auth._http import is_cross_site, safe_next
from pywire_auth.sessions import REFRESH_TOKEN_KEY, sign_in, sign_out

logger = logging.getLogger(__name__)

STATE_KEY = "_oauth_state"
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
        base_url: Optional[str] = None,
    ) -> None:
        self.providers = providers
        self.session_store = session_store
        self.session_ttl = session_ttl
        self.auth_channel = auth_channel
        self.default_next = default_next
        self.on_login = on_login
        self.on_logout = on_logout
        self.base_url = base_url.rstrip("/") if base_url else None

    def next_url(self, value: Optional[str]) -> str:
        """Where to send the browser next: a path on this site, never elsewhere."""
        return safe_next(value, self.default_next)

    def redirect_uri(self, request: Request, provider: str) -> str:
        """The callback URL the IdP sends the browser back to.

        Built from ``base_url`` when the app configured one. Otherwise it
        comes from the request's Host header, which the client chose; the
        IdP still only accepts callback URLs registered with it.
        """
        path = request.app.url_path_for("pywire_auth_callback", provider=provider)
        if self.base_url:
            return self.base_url + str(path)
        return str(path.make_absolute_url(base_url=request.base_url))

    async def after_login(self, principal: ClaimsPrincipal, request: Request) -> None:
        if self.on_login:
            try:
                await self.on_login(principal, request)
            except Exception:
                logger.warning("on_login callback raised", exc_info=True)

    async def after_logout(self, principal: ClaimsPrincipal, request: Request) -> None:
        if principal.is_authenticated and principal.user_id:
            try:
                await self.auth_channel.revoke(principal.user_id)
            except Exception:
                logger.warning("AuthChannel.revoke failed", exc_info=True)
        if self.on_logout:
            try:
                await self.on_logout(principal, request)
            except Exception:
                logger.warning("on_logout callback raised", exc_info=True)


def pkce_challenge(verifier: str) -> str:
    """The S256 PKCE ``code_challenge`` for ``verifier`` (RFC 7636)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_routes(
    ctx: _RouteContext, prefix: str, *, local_idp: Optional[Any] = None
) -> list:
    async def login(request: Request) -> Response:
        provider_name = request.path_params["provider"]
        provider = ctx.providers.get(provider_name)
        if provider is None:
            return Response("Unknown provider", status_code=404)

        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        redirect_uri = ctx.redirect_uri(request, provider_name)
        next_url = ctx.next_url(request.query_params.get("next"))

        session_id = _session_id_or_none(request)
        if session_id:
            data = await ctx.session_store.get(session_id) or {}
            pending = data.get(STATE_KEY)
            if not isinstance(pending, dict):
                pending = {}
            pending[state] = {
                "nonce": nonce,
                "code_verifier": code_verifier,
                "provider": provider_name,
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
            redirect_uri=redirect_uri,
            state=state,
            nonce=nonce,
            code_challenge=pkce_challenge(code_verifier),
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

        try:
            principal, token_data = await provider.exchange_code(
                code=code,
                redirect_uri=saved["redirect_uri"],
                state=returned_state or "",
                nonce=saved["nonce"],
                code_verifier=saved.get("code_verifier") or "",
            )
        except Exception as exc:
            logger.warning("OAuth exchange failed: %s", exc, exc_info=True)
            return Response("Login failed", status_code=400)

        # Upsert the user into the auth_store (if one is installed) and
        # merge any app-managed claims (role=admin, tier=beta, etc.) back
        # onto the principal so they survive logout/login.
        principal = await _upsert_oidc_user(request, provider_name, principal)

        # Consume this pending state (leave any other concurrent flows alone).
        pending.pop(returned_state, None)
        if pending:
            data[STATE_KEY] = pending
        else:
            data.pop(STATE_KEY, None)
        if token_data.get("refresh_token"):
            data[REFRESH_TOKEN_KEY] = token_data["refresh_token"]
        await sign_in(ctx, request, principal, data)
        await ctx.after_login(principal, request)
        return RedirectResponse(ctx.next_url(saved.get("next")), status_code=303)

    async def logout(request: Request) -> Response:
        # POST only, and only from this site: another site (or an <img>)
        # must not be able to sign the user out.
        if is_cross_site(request):
            return Response("Cross-site request refused", status_code=403)
        form = await request.form()
        next_url = ctx.next_url(
            request.query_params.get("next") or str(form.get("next") or "")
        )
        principal = await sign_out(ctx, request)
        await ctx.after_logout(principal, request)
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
            methods=["POST"],
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

    Users are found by ``(provider, subject)``: a subject is only unique
    within its provider, so ``github:123`` and ``google:123`` are different
    people. First login inserts a row with its own id and links it to the
    provider's subject. Every login merges the stored claims (app-added
    grants like ``role=admin``) on top of the provider-fresh claims (email,
    name, picture) and rebuilds the principal around the stored user id.

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

    existing = await store.find_by_provider(provider_name, subject)
    if existing is None:
        try:
            user_id = await store.create_user(
                email=provider_claims.get("email", ""),
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
            return principal
        existing = {"user_id": user_id, "claims": provider_claims}

    stored_user_id = str(existing["user_id"])
    # Stored claims win so app grants stick.
    merged = {**provider_claims, **dict(existing.get("claims") or {})}

    # Link (first login) or refresh the provider's view of its own claims.
    try:
        await store.link_provider(
            stored_user_id, provider_name, subject, provider_claims
        )
    except Exception:
        logger.warning("auth_store link_provider failed", exc_info=True)

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
