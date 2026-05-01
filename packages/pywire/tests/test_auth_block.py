"""{$auth} template-directive: parser → codegen → runtime coverage."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from pywire.auth import (
    AuthContext,
    Claim,
    ClaimsPrincipal,
    MemoryAuthChannel,
    PolicyEngine,
    reset_auth_context,
    set_auth_context,
)
from pywire.runtime.loader import get_loader


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _compile(body: str):
    src = f"---\n---\n{body}"
    with tempfile.NamedTemporaryFile("w", suffix=".wire", delete=False) as f:
        f.write(src)
        path = Path(f.name)
    try:
        return get_loader().load(path)
    finally:
        os.unlink(path)


def _admin_principal(has_admin: bool = True) -> ClaimsPrincipal:
    return ClaimsPrincipal(
        is_authenticated=True,
        name="test",
        user_id="x:1",
        claims=[Claim(type="role", value="admin")] if has_admin else [],
    )


def _engine_with_admin_policy() -> PolicyEngine:
    e = PolicyEngine()
    e.add_policy("AdminOnly", requires_claim=("role", "admin"))
    return e


async def _render_twice(cls, user: ClaimsPrincipal, engine: PolicyEngine):
    ctx = AuthContext(principal=user, engine=engine, channel=MemoryAuthChannel())
    tok = set_auth_context(ctx)
    try:
        page = cls(request=None, params={}, query={}, path={}, url=None)
        page.user = user
        pending = await page._render_template()
        for _ in range(5):
            await asyncio.sleep(0)
        resolved = await page._render_template()
        return pending, resolved
    finally:
        reset_auth_context(tok)


# ---------------------------------------------------------------------------
# parser / AST
# ---------------------------------------------------------------------------


def test_parser_emits_auth_attribute_with_policy():
    from pywire_parser import PyWireParser
    from pywire_parser.ast_nodes import AuthAttribute

    result = PyWireParser().parse(
        '---\n---\n{$auth policy="AdminOnly"}<p>x</p>{/auth}\n'
    )
    attrs = [
        a
        for n in result.template
        for a in n.special_attributes
        if isinstance(a, AuthAttribute)
    ]
    assert len(attrs) == 1
    assert attrs[0].policy == "AdminOnly"
    assert attrs[0].claims is None


def test_parser_emits_auth_attribute_with_claims():
    from pywire_parser import PyWireParser
    from pywire_parser.ast_nodes import AuthAttribute

    result = PyWireParser().parse(
        '---\n---\n{$auth claims=[("role","admin"), "tier"]}<p>x</p>{/auth}\n'
    )
    attrs = [
        a
        for n in result.template
        for a in n.special_attributes
        if isinstance(a, AuthAttribute)
    ]
    assert len(attrs) == 1
    assert attrs[0].policy is None
    assert attrs[0].claims == [("role", "admin"), ("tier", None)]


def test_parser_auth_block_captures_then_and_else_children():
    from pywire_parser import PyWireParser
    from pywire_parser.ast_nodes import (
        AuthAttribute,
        ElseAttribute,
        ThenAttribute,
    )

    result = PyWireParser().parse(
        '---\n---\n{$auth policy="P"}<p>allowed</p>{$else}<p>denied</p>{/auth}\n'
    )
    auth_nodes = [
        n
        for n in result.template
        if any(isinstance(a, AuthAttribute) for a in n.special_attributes)
    ]
    assert len(auth_nodes) == 1
    # Should contain an ElseAttribute marker among its children.
    has_else = any(
        any(isinstance(a, ElseAttribute) for a in c.special_attributes)
        for c in auth_nodes[0].children
    )
    assert has_else
    # $then variant
    result = PyWireParser().parse(
        '---\n---\n{$auth policy="P"}<p>pending</p>{$then ok}<p>{ok}</p>{/auth}\n'
    )
    auth_nodes = [
        n
        for n in result.template
        if any(isinstance(a, AuthAttribute) for a in n.special_attributes)
    ]
    has_then = any(
        any(isinstance(a, ThenAttribute) for a in c.special_attributes)
        for c in auth_nodes[0].children
    )
    assert has_then


# ---------------------------------------------------------------------------
# codegen + runtime
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_allowed_renders_allowed_body():
    cls = _compile(
        '<div>{$auth policy="AdminOnly"}<p>allowed</p>{$else}<p>denied</p>{/auth}</div>'
    )
    _, resolved = await _render_twice(
        cls, _admin_principal(True), _engine_with_admin_policy()
    )
    assert "<p>allowed</p>" in resolved
    assert "<p>denied</p>" not in resolved


@pytest.mark.asyncio
async def test_policy_denied_renders_denied_body():
    cls = _compile(
        '<div>{$auth policy="AdminOnly"}<p>allowed</p>{$else}<p>denied</p>{/auth}</div>'
    )
    _, resolved = await _render_twice(
        cls, _admin_principal(False), _engine_with_admin_policy()
    )
    assert "<p>denied</p>" in resolved
    assert "<p>allowed</p>" not in resolved


@pytest.mark.asyncio
async def test_no_else_branch_hides_denied_body():
    cls = _compile('<div>{$auth policy="AdminOnly"}<p>admin</p>{/auth}</div>')
    _, resolved = await _render_twice(
        cls, _admin_principal(False), _engine_with_admin_policy()
    )
    assert "<p>admin</p>" not in resolved


@pytest.mark.asyncio
async def test_claim_check_matches_value():
    cls = _compile(
        '<div>{$auth claims=[("role","admin")]}<p>a</p>{$else}<p>d</p>{/auth}</div>'
    )
    _, resolved = await _render_twice(cls, _admin_principal(True), PolicyEngine())
    assert "<p>a</p>" in resolved

    _, resolved = await _render_twice(cls, _admin_principal(False), PolicyEngine())
    assert "<p>d</p>" in resolved


@pytest.mark.asyncio
async def test_then_variant_binds_bool():
    cls = _compile(
        '<div>{$auth policy="AdminOnly"}<span>wait</span>{$then ok}<p>ok={ok}</p>{/auth}</div>'
    )
    _, allowed = await _render_twice(
        cls, _admin_principal(True), _engine_with_admin_policy()
    )
    assert "ok=True" in allowed
    _, denied = await _render_twice(
        cls, _admin_principal(False), _engine_with_admin_policy()
    )
    assert "ok=False" in denied


@pytest.mark.asyncio
async def test_authorizing_body_shows_on_first_render_before_task_completes():
    cls = _compile(
        '<div>{$auth policy="AdminOnly"}<span>pending-ui</span>{$then ok}<p>done</p>{/auth}</div>'
    )
    ctx = AuthContext(
        principal=_admin_principal(True),
        engine=_engine_with_admin_policy(),
        channel=MemoryAuthChannel(),
    )
    tok = set_auth_context(ctx)
    try:
        page = cls(request=None, params={}, query={}, path={}, url=None)
        page.user = _admin_principal(True)
        pending = await page._render_template()
        assert "pending-ui" in pending
    finally:
        reset_auth_context(tok)


@pytest.mark.asyncio
async def test_anonymous_with_no_args_denies():
    cls = _compile("<div>{$auth}<p>in</p>{$else}<p>out</p>{/auth}</div>")
    anon = ClaimsPrincipal(is_authenticated=False)
    _, resolved = await _render_twice(cls, anon, PolicyEngine())
    assert "<p>out</p>" in resolved


@pytest.mark.asyncio
async def test_unknown_policy_fails_closed():
    cls = _compile(
        '<div>{$auth policy="DoesNotExist"}<p>in</p>{$else}<p>out</p>{/auth}</div>'
    )
    _, resolved = await _render_twice(cls, _admin_principal(True), PolicyEngine())
    assert "<p>out</p>" in resolved


@pytest.mark.asyncio
async def test_nested_inside_for_loop():
    """One {$auth} per iteration evaluates independently."""
    cls = _compile(
        "<ul>"
        "{$for x in items}"
        '<li>{$auth claims=[("role","admin")]}[admin]{$else}[user]{/auth}{x}</li>'
        "{/for}"
        "</ul>"
    )
    ctx = AuthContext(
        principal=_admin_principal(True),
        engine=PolicyEngine(),
        channel=MemoryAuthChannel(),
    )
    tok = set_auth_context(ctx)
    try:
        page = cls(request=None, params={}, query={}, path={}, url=None)
        page.user = _admin_principal(True)
        page.items = ["a", "b"]
        _ = await page._render_template()
        for _ in range(10):
            await asyncio.sleep(0)
        resolved = await page._render_template()
        assert resolved.count("[admin]") == 2
    finally:
        reset_auth_context(tok)
