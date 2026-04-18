"""Authorization policies.

A policy is a named predicate evaluated against a ``PolicyContext``. The
engine supports three registration shapes:

1. A function passed as ``fn=`` (sync or async).
2. A simple ``requires_claim=(type, value|None)`` declaration.
3. ``requires_authenticated=True`` to express the trivial "must be logged in"
   policy for reuse by name.

A decorator form is also exposed via ``engine.policy(name)``.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Optional,
    Protocol,
    Tuple,
    Union,
    runtime_checkable,
)

from pywire.auth.principal import ClaimsPrincipal


@dataclass
class PolicyContext:
    """Per-evaluation envelope passed to policies.

    ``request`` is typed loosely to avoid a hard dependency on Starlette
    types at this layer — policies that need request-scoped data can
    access attributes directly.
    """

    principal: ClaimsPrincipal
    request: Any = None


@runtime_checkable
class Policy(Protocol):
    """Structural shape for any policy callable."""

    async def __call__(self, ctx: PolicyContext) -> bool: ...


PolicyLike = Union[
    Policy,
    Callable[[PolicyContext], bool],
    Callable[[PolicyContext], Awaitable[bool]],
]


class PolicyDeniedError(Exception):
    """Raised when a policy denies access and no redirect is configured."""


class PolicyEngine:
    """Named policy registry with sync/async evaluation."""

    def __init__(self) -> None:
        self._policies: Dict[str, PolicyLike] = {}

    def add_policy(
        self,
        name: str,
        *,
        fn: Optional[PolicyLike] = None,
        requires_claim: Optional[Tuple[str, Optional[str]]] = None,
        requires_authenticated: bool = False,
    ) -> None:
        """Register a policy.

        Exactly one of ``fn``, ``requires_claim``, or
        ``requires_authenticated`` must be provided.
        """
        count = sum(1 for x in (fn, requires_claim, requires_authenticated) if x)
        if count != 1:
            raise ValueError(
                "add_policy requires exactly one of fn, requires_claim, "
                "or requires_authenticated"
            )

        if fn is not None:
            self._policies[name] = fn
            return

        if requires_claim is not None:
            claim_type, claim_value = requires_claim

            async def _check_claim(ctx: PolicyContext) -> bool:
                return ctx.principal.has_claim(claim_type, claim_value)

            self._policies[name] = _check_claim
            return

        async def _check_authn(ctx: PolicyContext) -> bool:
            return ctx.principal.is_authenticated

        self._policies[name] = _check_authn

    def policy(self, name: str) -> Callable[[PolicyLike], PolicyLike]:
        """Decorator form of ``add_policy(name, fn=...)``."""

        def decorator(fn: PolicyLike) -> PolicyLike:
            self._policies[name] = fn
            return fn

        return decorator

    async def evaluate(self, name: str, ctx: PolicyContext) -> bool:
        """Run the named policy. Raises ``KeyError`` for unknown names."""
        fn = self._policies.get(name)
        if fn is None:
            raise KeyError(f"Unknown policy: {name!r}")
        result = fn(ctx)
        if inspect.isawaitable(result):
            result = await result
        return bool(result)

    def has_policy(self, name: str) -> bool:
        return name in self._policies
