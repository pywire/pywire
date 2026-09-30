"""Handlers wired only inside ``{$auth}`` run only for users the block allows."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

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
from pywire.runtime.loader import get_loader

PAGE = """---
calls = []

def nuke():
    calls.append("nuke")

def everyone():
    calls.append("everyone")

def shared():
    calls.append("shared")

def row_action():
    calls.append("row")
---
{$auth policy="AdminOnly"}
  <button @click={nuke}>Nuke</button>
  <button @click={shared}>Shared</button>
  <button @click={calls.append("inline")}>Inline</button>
{$else}
  <p>Admins only</p>
  <button @click={everyone}>Everyone</button>
{/auth}
<button @click={shared}>Shared outside</button>
{$for tier in ["gold"]}
  {$auth claims=[("tier", tier)]}
    <button @click={row_action}>Row</button>
  {/auth}
{/for}
"""


def _load():
    with tempfile.NamedTemporaryFile("w", suffix=".wire", delete=False) as f:
        f.write(PAGE)
        path = Path(f.name)
    try:
        return get_loader().load(path)
    finally:
        os.unlink(path)


def _user(*claims: tuple) -> ClaimsPrincipal:
    return ClaimsPrincipal(
        is_authenticated=True,
        name="u",
        user_id="x:1",
        claims=[Claim(type=t, value=v) for t, v in claims],
    )


async def _page(user: ClaimsPrincipal):
    engine = PolicyEngine()
    engine.add_policy("AdminOnly", requires_claim=("role", "admin"))
    token = set_auth_context(
        AuthContext(principal=user, engine=engine, channel=MemoryAuthChannel())
    )
    page = _load()(request=None, params={}, query={}, path={}, url=None)
    page.user = user
    page._auth_inline = lambda: True  # resolve {$auth} within the render
    await page._render_template()
    return page, token


def _handler(page, text: str) -> str:
    """The generated wrapper for the one gated inline expression."""
    (name,) = [n for n in type(page).__auth_handlers__ if n.startswith("_handler_")]
    return name


@pytest.mark.asyncio
async def test_gated_handlers_refused_for_users_the_block_denies():
    page, token = await _page(ANONYMOUS)
    try:
        gated = type(page).__auth_handlers__
        assert "nuke" in gated
        assert "shared" not in gated  # also wired outside the block
        assert "everyone" not in gated  # the $else branch renders for them
        for name in ("nuke", _handler(page, "inline")):
            with pytest.raises(ValueError, match="not allowed"):
                await page._dispatch_handler(name, {})
        await page._dispatch_handler("shared", {})
        await page._dispatch_handler("everyone", {})
        assert page.calls == ["shared", "everyone"]
    finally:
        reset_auth_context(token)


@pytest.mark.asyncio
async def test_gated_handlers_run_for_users_the_block_allows():
    page, token = await _page(_user(("role", "admin")))
    try:
        await page._dispatch_handler("nuke", {})
        await page._dispatch_handler(_handler(page, "inline"), {})
        assert page.calls[0] == "nuke" and len(page.calls) == 2  # both ran
    finally:
        reset_auth_context(token)


@pytest.mark.asyncio
async def test_revoked_claims_close_the_gate_without_a_rerender():
    page, token = await _page(_user(("role", "admin")))
    try:
        page.user = _user()  # live-auth downgrade
        with pytest.raises(ValueError, match="not allowed"):
            await page._dispatch_handler("nuke", {})
    finally:
        reset_auth_context(token)


@pytest.mark.asyncio
async def test_per_render_claims_are_checked_per_rendered_block():
    gold, token = await _page(_user(("tier", "gold")))
    try:
        assert type(gold).__auth_handlers__["row_action"][0][0][0] == "region"
        await gold._dispatch_handler("row_action", {})
        assert gold.calls == ["row"]
    finally:
        reset_auth_context(token)
    plain, token = await _page(_user())
    try:
        with pytest.raises(ValueError, match="not allowed"):
            await plain._dispatch_handler("row_action", {})
    finally:
        reset_auth_context(token)
