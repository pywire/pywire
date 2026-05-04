"""Resolved configuration for ``connect_secure()``.

Keyword arguments to :func:`connect_secure` always win; missing values
fall back to ``PYWIRE_SECURE_*`` environment variables read through
:func:`pywire.config.env`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class SecureConfig:
    """Final, resolved settings used by ``connect_secure``."""

    # Feature flags
    csrf: bool = True
    headers: bool = True
    rate_limit: bool = False
    https_redirect: bool = False

    # CSRF
    secret_key: Optional[str] = None
    csrf_token_ttl: int = 3600
    csrf_skip_paths: tuple[str, ...] = ("/_pywire",)

    # Security headers
    x_content_type_options: str = "nosniff"
    x_frame_options: str = "SAMEORIGIN"
    referrer_policy: str = "strict-origin-when-cross-origin"
    permissions_policy: str = "camera=(), microphone=(), geolocation=()"
    hsts: bool = False
    hsts_max_age: int = 31_536_000
    hsts_include_subdomains: bool = True
    hsts_preload: bool = False
    csp: Optional[str] = None

    # Rate limit
    rate_limit_default: str = "100/minute"


def _env_bool(name: str, default: bool) -> bool:
    from pywire.config import env

    raw = env(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def resolve_config(
    *,
    csrf: Optional[bool] = None,
    headers: Optional[bool] = None,
    rate_limit: Optional[bool] = None,
    https_redirect: Optional[bool] = None,
    secret_key: Optional[str] = None,
    csrf_token_ttl: Optional[int] = None,
    csrf_skip_paths: Optional[tuple[str, ...]] = None,
    x_frame_options: Optional[str] = None,
    referrer_policy: Optional[str] = None,
    permissions_policy: Optional[str] = None,
    hsts: Optional[bool] = None,
    hsts_max_age: Optional[int] = None,
    hsts_include_subdomains: Optional[bool] = None,
    hsts_preload: Optional[bool] = None,
    csp: Any = None,
    rate_limit_default: Optional[str] = None,
) -> SecureConfig:
    """Merge kwargs with ``PYWIRE_SECURE_*`` env vars and PyWire's session
    secret, returning a fully populated :class:`SecureConfig`.

    ``csp`` accepts a raw string or any object with a ``build() -> str``
    method (notably :class:`pywire_secure.headers.CSPBuilder`).
    """
    defaults = SecureConfig()

    csp_value: Optional[str]
    if csp is None:
        csp_value = None
    elif isinstance(csp, str):
        csp_value = csp
    else:
        builder = getattr(csp, "build", None)
        csp_value = str(builder()) if callable(builder) else str(csp)

    return SecureConfig(
        csrf=csrf
        if csrf is not None
        else _env_bool("PYWIRE_SECURE_CSRF", defaults.csrf),
        headers=headers
        if headers is not None
        else _env_bool("PYWIRE_SECURE_HEADERS", defaults.headers),
        rate_limit=rate_limit
        if rate_limit is not None
        else _env_bool("PYWIRE_SECURE_RATE_LIMIT", defaults.rate_limit),
        https_redirect=https_redirect
        if https_redirect is not None
        else _env_bool("PYWIRE_SECURE_HTTPS_REDIRECT", defaults.https_redirect),
        secret_key=secret_key,
        csrf_token_ttl=csrf_token_ttl
        if csrf_token_ttl is not None
        else defaults.csrf_token_ttl,
        csrf_skip_paths=csrf_skip_paths
        if csrf_skip_paths is not None
        else defaults.csrf_skip_paths,
        x_frame_options=x_frame_options
        if x_frame_options is not None
        else defaults.x_frame_options,
        referrer_policy=referrer_policy
        if referrer_policy is not None
        else defaults.referrer_policy,
        permissions_policy=permissions_policy
        if permissions_policy is not None
        else defaults.permissions_policy,
        hsts=hsts
        if hsts is not None
        else _env_bool("PYWIRE_SECURE_HSTS", defaults.hsts),
        hsts_max_age=hsts_max_age
        if hsts_max_age is not None
        else defaults.hsts_max_age,
        hsts_include_subdomains=hsts_include_subdomains
        if hsts_include_subdomains is not None
        else defaults.hsts_include_subdomains,
        hsts_preload=hsts_preload
        if hsts_preload is not None
        else defaults.hsts_preload,
        csp=csp_value,
        rate_limit_default=rate_limit_default
        if rate_limit_default is not None
        else defaults.rate_limit_default,
    )
