"""Auth guard — enforces !auth directives.

Invoked from ``BasePage.render()`` before user ``@before_load`` hooks. If
access is denied, returns a ``RedirectResponse``; the page's ``render()``
propagates that back to the transport without ever executing user code.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from starlette.responses import RedirectResponse, Response

from pywire.auth.context import get_auth_context
from pywire.auth.policy import PolicyContext
from pywire.auth.principal import ANONYMOUS, ClaimsPrincipal

DEFAULT_REDIRECT = "/login"


async def run_auth_guard(page: Any) -> Optional[Response]:
    """Return a redirect response if access is denied; None if allowed."""
    cls = page.__class__
    if not getattr(cls, "__auth_required__", False):
        return None

    principal = _resolve_principal(page)
    redirect = getattr(cls, "__auth_redirect__", None) or DEFAULT_REDIRECT
    policy_name: Optional[str] = getattr(cls, "__auth_policy__", None)
    required_claims: List[Tuple[str, str]] = getattr(cls, "__auth_claims__", []) or []

    # Bare !auth — authentication alone
    if not policy_name and not required_claims:
        if not principal.is_authenticated:
            return _deny(redirect)
        return None

    # Inline claim checks
    for claim_type, claim_value in required_claims:
        match_value: Optional[str] = claim_value or None
        if not principal.has_claim(claim_type, match_value):
            return _deny(redirect)

    # Named policy (fails closed when engine missing or policy unknown)
    if policy_name:
        ctx = get_auth_context()
        if ctx is None:
            return _deny(redirect)
        policy_ctx = PolicyContext(
            principal=principal, request=getattr(page, "request", None)
        )
        try:
            allowed = await ctx.engine.evaluate(policy_name, policy_ctx)
        except KeyError:
            return _deny(redirect)
        if not allowed:
            return _deny(redirect)

    return None


def _resolve_principal(page: Any) -> ClaimsPrincipal:
    principal = getattr(page, "user", None)
    if isinstance(principal, ClaimsPrincipal):
        return principal
    return ANONYMOUS


def _deny(redirect: str) -> Response:
    return RedirectResponse(redirect, status_code=303)
