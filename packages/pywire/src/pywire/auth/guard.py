"""Auth guard — enforces !auth directives and backs the {$auth} directive.

Invoked from ``BasePage.render()`` before user ``@before_load`` hooks. If
access is denied, returns a ``RedirectResponse``; the page's ``render()``
propagates that back to the transport without ever executing user code.

``evaluate_auth`` is the same decision as ``run_auth_guard`` but returns a
bool — used by the ``{$auth}`` template directive to gate a region
without redirecting the whole page.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, List, Optional, Tuple

from starlette.responses import RedirectResponse, Response

from pywire.auth.context import get_auth_context
from pywire.auth.policy import PolicyContext
from pywire.auth.principal import ANONYMOUS, ClaimsPrincipal

logger = logging.getLogger(__name__)

DEFAULT_REDIRECT = "/login"


async def evaluate_auth(
    principal: ClaimsPrincipal,
    *,
    policy: Optional[str] = None,
    claims: Optional[Iterable[Tuple[str, Optional[str]]]] = None,
    request: Any = None,
) -> bool:
    """Return True if the principal satisfies policy + claims, else False.

    Same semantics as ``run_auth_guard``'s internal decision, but returns
    a bool instead of an HTTP redirect. Used by the ``{$auth}`` template
    directive. Policy errors (missing engine, unknown policy name, user
    callable raising) fail closed to ``False``.

    - No args ``evaluate_auth(principal)`` checks only
      ``principal.is_authenticated``.
    - Every claim in ``claims`` must match (type + optional value).
    - ``policy`` is looked up on the ambient ``AuthContext.engine``.
    """
    required_claims: List[Tuple[str, Optional[str]]] = (
        list(claims) if claims else []
    )

    if not policy and not required_claims:
        return bool(principal.is_authenticated)

    for claim_type, claim_value in required_claims:
        match_value: Optional[str] = claim_value or None
        if not principal.has_claim(claim_type, match_value):
            return False

    if policy:
        ctx = get_auth_context()
        if ctx is None:
            return False
        policy_ctx = PolicyContext(principal=principal, request=request)
        try:
            allowed = await ctx.engine.evaluate(policy, policy_ctx)
        except KeyError:
            return False
        except Exception:
            logger.warning(
                "policy %r raised during evaluation; failing closed",
                policy,
                exc_info=True,
            )
            return False
        if not allowed:
            return False

    return True


async def run_auth_guard(page: Any) -> Optional[Response]:
    """Return a redirect response if access is denied; None if allowed."""
    cls = page.__class__
    if not getattr(cls, "__auth_required__", False):
        return None

    principal = _resolve_principal(page)
    redirect = getattr(cls, "__auth_redirect__", None) or DEFAULT_REDIRECT
    policy_name: Optional[str] = getattr(cls, "__auth_policy__", None)
    required_claims: List[Tuple[str, str]] = (
        getattr(cls, "__auth_claims__", []) or []
    )

    allowed = await evaluate_auth(
        principal,
        policy=policy_name,
        claims=required_claims,
        request=getattr(page, "request", None),
    )
    if allowed:
        return None
    return _deny(redirect)


def _resolve_principal(page: Any) -> ClaimsPrincipal:
    principal = getattr(page, "user", None)
    if isinstance(principal, ClaimsPrincipal):
        return principal
    return ANONYMOUS


def _deny(redirect: str) -> Response:
    return RedirectResponse(redirect, status_code=303)
