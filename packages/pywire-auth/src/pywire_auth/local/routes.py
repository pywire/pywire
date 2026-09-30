"""Default HTTP routes for LocalIdP.

Mounted by :func:`pywire_auth.integration.connect_auth` when a
``local_idp=`` argument is passed. Mirrors the OIDC route shape at
``/auth/{provider}/{action}`` — the "provider" here is the literal
string ``local``.

- ``POST {prefix}/local/register`` — create user, sign in
- ``POST {prefix}/local/login``    — verify password, sign in
- ``POST {prefix}/local/token``    — issue id_token for the current principal
- ``POST {prefix}/local/verify-token`` — verify a JWT (JSON body: {"token": ...})
- ``POST {prefix}/local/revoke``   — clear session + fire channel.revoke

Apps that want different UX (e.g. a GET login page with an HTML form)
render the UI themselves and POST to these routes.
"""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from pywire.auth import ANONYMOUS, read_principal_from_session

from pywire_auth._http import is_cross_site, safe_next
from pywire_auth.local.idp import normalize_email
from pywire_auth.sessions import sign_in, sign_out

logger = logging.getLogger(__name__)


def _session_id(request: Request) -> Optional[str]:
    return request.scope.get("pywire_session_id")


async def _next_from_form_or_query(request: Request) -> Optional[str]:
    """Resolve ``?next=`` or form-field ``next``; None if neither is present."""
    value = request.query_params.get("next")
    if value:
        return value
    if request.method == "POST":
        try:
            form = await request.form()
        except Exception:
            return None
        raw = form.get("next")
        return str(raw) if raw else None
    return None


def _error_redirect(request: Request, form: Any, fallback: str, error: str) -> str:
    """Build a redirect URL for the error case.

    Priority:
    1. ``error_next`` form field (explicit from the page that posted)
    2. ``Referer`` header (the form page the user came from)
    3. ``fallback`` (framework-provided default, e.g. ``/auth/logout``)

    The ``error`` code is appended as a query param. Only paths on this
    site are used: the form field must be one, and the Referer must name
    this host.
    """
    explicit = safe_next(str(form.get("error_next") or "").strip() if form else "", "")
    if explicit:
        return _with_query(explicit, "error", error)
    referer = request.headers.get("referer", "")
    if referer:
        try:
            from urllib.parse import urlparse

            parsed = urlparse(referer)
            path = safe_next(parsed.path, "")
            if parsed.netloc == request.url.netloc and path:
                return _with_query(path, "error", error)
        except Exception:
            pass
    return _with_query(fallback, "error", error)


def _with_query(path: str, key: str, value: str) -> str:
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}{key}={value}"


def build_local_routes(ctx: Any, prefix: str, idp: Any) -> List[Route]:
    """Return the Starlette routes for LocalIdP.

    ``ctx`` is the ``_RouteContext`` from the main routes module.
    ``idp`` is the configured ``LocalIdP`` instance.
    """

    def client_key(request: Request) -> str:
        return f"client:{request.client.host if request.client else ''}"

    async def register(request: Request) -> Response:
        if is_cross_site(request):
            return Response("Cross-site request refused", status_code=403)
        form = await request.form()
        email = str(form.get("email") or "").strip()
        password = str(form.get("password") or "")
        name = str(form.get("name") or "").strip()
        next_url = ctx.next_url(
            request.query_params.get("next") or str(form.get("next") or "")
        )

        fallback = f"{prefix}/logout"  # always present
        if not email or not password:
            return RedirectResponse(
                _error_redirect(request, form, fallback, "missing"), status_code=303
            )
        # Every registration hashes a password: count them per client.
        if idp.throttle is not None:
            if idp.throttle.blocked(client_key(request)):
                return RedirectResponse(
                    _error_redirect(request, form, fallback, "throttled"),
                    status_code=303,
                )
            idp.throttle.hit(client_key(request))

        # Only the email becomes a claim. Anything else the form carries
        # (`role`, `email_verified`, ...) is the visitor's say-so: roles
        # are granted server-side with AuthActions, and an email is
        # verified only by proving control of it.
        try:
            user_id = await idp.create_user(
                email=email, password=password, name=name, claims={"email": email}
            )
        except ValueError:
            return RedirectResponse(
                _error_redirect(request, form, fallback, "exists"), status_code=303
            )
        except Exception:
            logger.warning("LocalIdP create_user failed", exc_info=True)
            return RedirectResponse(
                _error_redirect(request, form, fallback, "unknown"), status_code=303
            )

        principal = await idp.principal_for_user(user_id)
        if principal is None:
            return RedirectResponse(
                f"{prefix}/local/register?error=unknown", status_code=303
            )

        await sign_in(ctx, request, principal)
        await ctx.after_login(principal, request)
        return RedirectResponse(next_url, status_code=303)

    async def login(request: Request) -> Response:
        if is_cross_site(request):
            return Response("Cross-site request refused", status_code=403)
        form = await request.form()
        email = str(form.get("email") or "").strip()
        password = str(form.get("password") or "")
        next_url = ctx.next_url(
            request.query_params.get("next") or str(form.get("next") or "")
        )

        keys = (client_key(request), f"email:{normalize_email(email)}")
        if idp.throttle is not None and idp.throttle.blocked(*keys):
            return RedirectResponse(
                _error_redirect(request, form, f"{prefix}/logout", "throttled"),
                status_code=303,
            )
        principal = await idp.verify_credentials(email=email, password=password)
        if principal is None:
            if idp.throttle is not None:
                idp.throttle.hit(*keys)
            return RedirectResponse(
                _error_redirect(request, form, f"{prefix}/logout", "invalid"),
                status_code=303,
            )
        if idp.throttle is not None:
            idp.throttle.reset(keys[1])

        await sign_in(ctx, request, principal)
        await ctx.after_login(principal, request)
        return RedirectResponse(next_url, status_code=303)

    async def token(request: Request) -> Response:
        sid = _session_id(request)
        if not sid:
            return JSONResponse({"error": "no session"}, status_code=400)
        data = await ctx.session_store.get(sid) or {}
        principal = read_principal_from_session(data) or ANONYMOUS
        if not principal.is_authenticated:
            return JSONResponse({"error": "not authenticated"}, status_code=401)

        # user_id is prefixed like "local:<uuid>"; issue_id_token expects
        # the bare subject.
        raw_uid = principal.user_id.split(":", 1)[-1] if principal.user_id else ""
        if not raw_uid:
            return JSONResponse({"error": "missing user_id"}, status_code=400)

        claims_map = {c.type: c.value for c in principal.claims if c.type != "sub"}
        jwt = idp.issue_id_token(user_id=raw_uid, claims=claims_map, ttl=600)
        decoded = idp.verify_id_token(jwt)
        return JSONResponse({"token": jwt, "decoded": decoded})

    async def verify_token(request: Request) -> Response:
        body = await request.body()
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return JSONResponse({"valid": False, "error": "bad json"}, status_code=400)
        raw_token = str(payload.get("token") or "").strip()
        if not raw_token:
            return JSONResponse(
                {"valid": False, "error": "missing token"}, status_code=400
            )
        decoded = idp.verify_id_token(raw_token)
        if decoded is None:
            return JSONResponse({"valid": False})
        return JSONResponse({"valid": True, "decoded": decoded})

    async def revoke(request: Request) -> Response:
        if is_cross_site(request):
            return Response("Cross-site request refused", status_code=403)
        next_url = ctx.next_url(await _next_from_form_or_query(request))
        principal = await sign_out(ctx, request)
        await ctx.after_logout(principal, request)
        return RedirectResponse(next_url, status_code=303)

    return [
        Route(
            f"{prefix}/local/register",
            register,
            methods=["POST"],
            name="pywire_auth_local_register",
        ),
        Route(
            f"{prefix}/local/login",
            login,
            methods=["POST"],
            name="pywire_auth_local_login",
        ),
        Route(
            f"{prefix}/local/token",
            token,
            methods=["POST"],
            name="pywire_auth_local_token",
        ),
        Route(
            f"{prefix}/local/verify-token",
            verify_token,
            methods=["POST"],
            name="pywire_auth_local_verify_token",
        ),
        Route(
            f"{prefix}/local/revoke",
            revoke,
            methods=["POST"],
            name="pywire_auth_local_revoke",
        ),
    ]
