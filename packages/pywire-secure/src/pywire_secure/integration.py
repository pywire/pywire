"""Single integration entry point — ``connect_secure(app, ...)``.

Installs the middleware bundle (CSRF, security headers, rate limiting,
HTTPS redirect) onto a PyWire app and patches ``app._handle_request``
so the post-render HTML pass also injects CSRF token markers.

Stack order on a fully-enabled call (outermost → innermost):

    HTTPSRedirectMiddleware   (redirect before any work happens)
    SecurityHeadersMiddleware (headers on every response)
    SessionMiddleware          (already installed by PyWire when needed)
    CSRFMiddleware             (validates state-mutating requests)
    [PyWire app]

Starlette's ``add_middleware`` prepends to the user list, so installing
in *innermost-first* order produces the stack above.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from pywire_secure.config import resolve_config
from pywire_secure.csrf import generate_token
from pywire_secure.headers import SecurityHeadersMiddleware
from pywire_secure.injection import inject_csrf_tokens
from pywire_secure.middleware import CSRFMiddleware


def connect_secure(
    app: Any,
    *,
    csrf: Optional[bool] = None,
    headers: Optional[bool] = None,
    rate_limit: Optional[bool] = None,
    https_redirect: Optional[bool] = None,
    secret_key: Optional[str] = None,
    csrf_token_ttl: Optional[int] = None,
    csrf_skip_paths: Optional[Sequence[str]] = None,
    x_frame_options: Optional[str] = None,
    referrer_policy: Optional[str] = None,
    permissions_policy: Optional[str] = None,
    hsts: Optional[bool] = None,
    hsts_max_age: Optional[int] = None,
    hsts_include_subdomains: Optional[bool] = None,
    hsts_preload: Optional[bool] = None,
    csp: Any = None,
    rate_limit_default: Optional[str] = None,
) -> None:
    """Attach pywire-secure middleware to a PyWire app.

    Pass a flag explicitly to override the env-var default. Omitting a
    flag accepts the default (CSRF + headers on, rate-limit + HTTPS
    redirect off).
    """
    cfg = resolve_config(
        csrf=csrf,
        headers=headers,
        rate_limit=rate_limit,
        https_redirect=https_redirect,
        secret_key=secret_key,
        csrf_token_ttl=csrf_token_ttl,
        csrf_skip_paths=tuple(csrf_skip_paths) if csrf_skip_paths is not None else None,
        x_frame_options=x_frame_options,
        referrer_policy=referrer_policy,
        permissions_policy=permissions_policy,
        hsts=hsts,
        hsts_max_age=hsts_max_age,
        hsts_include_subdomains=hsts_include_subdomains,
        hsts_preload=hsts_preload,
        csp=csp,
        rate_limit_default=rate_limit_default,
    )

    effective_secret = _resolve_secret(app, cfg.secret_key)
    if cfg.csrf and not effective_secret:
        raise RuntimeError(
            "connect_secure requires a secret_key (or PYWIRE_SESSION_SECRET) "
            "when csrf=True. Set PyWire(..., session_secret=...) or set the "
            "env var, then call connect_secure() again."
        )

    if cfg.https_redirect:
        from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

        app.add_middleware(HTTPSRedirectMiddleware)

    if cfg.headers:
        hsts_value = _build_hsts(cfg) if cfg.hsts else None
        app.add_middleware(
            SecurityHeadersMiddleware,
            x_frame_options=cfg.x_frame_options,
            referrer_policy=cfg.referrer_policy,
            permissions_policy=cfg.permissions_policy,
            hsts=hsts_value,
            csp=cfg.csp,
        )

    if cfg.csrf and effective_secret:
        app.add_middleware(
            CSRFMiddleware,
            secret_key=effective_secret,
            pywire_app=app,
            token_ttl=cfg.csrf_token_ttl,
            skip_paths=cfg.csrf_skip_paths,
        )
        _patch_csrf_injection(app, effective_secret, cfg.csrf_token_ttl)

    if cfg.rate_limit:
        from pywire_secure.ratelimit import install_rate_limit

        install_rate_limit(app, default_limit=cfg.rate_limit_default)


def _resolve_secret(app: Any, explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    candidate = getattr(app, "_session_secret", None)
    if candidate:
        return candidate
    from pywire.config import env

    return env("PYWIRE_SESSION_SECRET")


def _build_hsts(cfg: Any) -> str:
    parts = [f"max-age={cfg.hsts_max_age}"]
    if cfg.hsts_include_subdomains:
        parts.append("includeSubDomains")
    if cfg.hsts_preload:
        parts.append("preload")
    return "; ".join(parts)


def _patch_csrf_injection(app: Any, secret: str, ttl: int) -> None:
    """Wrap ``app._handle_request`` so HTML responses get CSRF token
    injections (meta tag, JS global, hidden form input).

    Instance-level monkey-patch — does not affect other PyWire instances
    in the same process. The wrapper bails out cleanly when the response
    is not HTML or the request has no session id, so it is safe even if
    a future framework version emits unfamiliar response shapes.
    """
    original = app._handle_request

    async def patched(request: Any) -> Any:
        response = await original(request)
        media = getattr(response, "media_type", None)
        if media != "text/html":
            return response
        body_attr = getattr(response, "body", None)
        if not isinstance(body_attr, (bytes, bytearray)):
            return response
        session_id = request.scope.get("pywire_session_id", "") or ""
        if not session_id:
            return response

        # session_id is non-empty here (guarded above), so generate_token
        # always returns a populated token.
        token = generate_token(session_id, secret, ttl=ttl)
        request.state.csrf_token = token

        try:
            html = bytes(body_attr).decode("utf-8")
        except UnicodeDecodeError:
            return response
        injected = inject_csrf_tokens(html, token)
        if injected == html:
            return response

        from starlette.responses import Response as _Response

        new_response = _Response(
            injected,
            status_code=getattr(response, "status_code", 200),
            media_type="text/html",
        )
        # Preserve any headers the original response carried (cookies,
        # redirects, etc.) by copying them across.
        try:
            for key, value in response.headers.items():
                if key.lower() in ("content-length", "content-type"):
                    continue
                new_response.headers[key] = value
        except AttributeError:
            pass
        return new_response

    app._handle_request = patched
