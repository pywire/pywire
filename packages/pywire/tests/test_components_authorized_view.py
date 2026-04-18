"""Tests for the <AuthorizedView> built-in component."""

from __future__ import annotations

import pytest

from pywire.auth import (
    ANONYMOUS,
    AuthContext,
    Claim,
    ClaimsPrincipal,
    MemoryAuthChannel,
    PolicyEngine,
    reset_auth_context,
    set_auth_context,
)
from pywire.components import AuthorizedView
from pywire.runtime.page import BasePage


def _make_view(
    *,
    parent: BasePage | None = None,
    policy: str | None = None,
    claims: list[tuple[str, str]] | None = None,
) -> BasePage:
    view = AuthorizedView(
        None,
        {},
        {},
        policy=policy,
        claims=claims,
        __is_component__=True,
        _parent_page=parent,
    )
    return view


class _FakeParent:
    """Minimal parent stand-in — only ``user`` and ``request`` are needed."""

    def __init__(self, user: object) -> None:
        self.user = user
        self.request = None


def test_component_loads() -> None:
    assert issubclass(AuthorizedView, BasePage)


@pytest.mark.asyncio
async def test_evaluate_requires_auth_by_default() -> None:
    parent = _FakeParent(ANONYMOUS)
    view = _make_view(parent=parent)
    self_arg = view  # _evaluate closes over `self`
    assert await view._evaluate() is False  # anonymous

    parent.user = ClaimsPrincipal(is_authenticated=True)
    view = _make_view(parent=parent)
    assert await view._evaluate() is True


@pytest.mark.asyncio
async def test_evaluate_claims_inline() -> None:
    parent = _FakeParent(
        ClaimsPrincipal(
            is_authenticated=True, claims=[Claim(type="role", value="editor")]
        )
    )
    view = _make_view(parent=parent, claims=[("role", "admin")])
    assert await view._evaluate() is False

    parent.user = ClaimsPrincipal(
        is_authenticated=True, claims=[Claim(type="role", value="admin")]
    )
    view = _make_view(parent=parent, claims=[("role", "admin")])
    assert await view._evaluate() is True


@pytest.mark.asyncio
async def test_evaluate_named_policy() -> None:
    engine = PolicyEngine()
    engine.add_policy("AdminOnly", requires_claim=("role", "admin"))

    parent = _FakeParent(
        ClaimsPrincipal(
            is_authenticated=True, claims=[Claim(type="role", value="admin")]
        )
    )
    view = _make_view(parent=parent, policy="AdminOnly")

    ctx = AuthContext(principal=parent.user, engine=engine, channel=MemoryAuthChannel())
    token = set_auth_context(ctx)
    try:
        assert await view._evaluate() is True
    finally:
        reset_auth_context(token)


@pytest.mark.asyncio
async def test_evaluate_named_policy_without_engine_fails_closed() -> None:
    parent = _FakeParent(ClaimsPrincipal(is_authenticated=True))
    view = _make_view(parent=parent, policy="AdminOnly")
    assert await view._evaluate() is False


@pytest.mark.asyncio
async def test_evaluate_unknown_policy_fails_closed() -> None:
    engine = PolicyEngine()
    parent = _FakeParent(ClaimsPrincipal(is_authenticated=True))
    view = _make_view(parent=parent, policy="DoesNotExist")

    ctx = AuthContext(principal=parent.user, engine=engine, channel=MemoryAuthChannel())
    token = set_auth_context(ctx)
    try:
        assert await view._evaluate() is False
    finally:
        reset_auth_context(token)


@pytest.mark.asyncio
async def test_evaluate_missing_parent_treats_as_anonymous() -> None:
    view = _make_view(parent=None)
    assert await view._evaluate() is False
