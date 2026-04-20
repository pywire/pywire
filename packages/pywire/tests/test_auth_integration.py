"""BasePage auth guard short-circuit + WebSocketHandler._resolve_user."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from pywire.auth import ANONYMOUS, Claim, ClaimsPrincipal
from pywire.runtime.loader import PageLoader
from pywire.runtime.websocket import WebSocketHandler


class TestRenderAuthGuard:
    def setup_method(self) -> None:
        self.loader = PageLoader()
        self.temp_dir = tempfile.TemporaryDirectory()

    def teardown_method(self) -> None:
        self.temp_dir.cleanup()
        self.loader.invalidate_cache()

    def _make_page(self, content: str) -> Any:
        path = Path(self.temp_dir.name) / "temp.wire"
        path.write_text(content)
        page_class = self.loader.load(path)
        request = MagicMock()
        request.app.state.enable_pjax = False
        request.app.state.wire._get_client_script_url.return_value = "/s.js"
        return page_class(request, {}, {})

    @pytest.mark.asyncio
    async def test_guard_short_circuits_before_load(self) -> None:
        """!auth deny must skip @before_load + @init hooks entirely."""
        content = """
!auth
---
__no_spa__ = True
self.log = []

@before_load
def bl(self):
    self.log.append('before_load')

@init
def i(self):
    self.log.append('init')
---

<p>Secret</p>
"""
        page = self._make_page(content)
        page.user = ANONYMOUS

        response = await page.render(init=True)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"
        # Hooks never ran — the whole point of fail-closed.
        assert page.log == []
        # _pending_navigation mirror set for WS transport.
        assert page._pending_navigation == "/login"

    @pytest.mark.asyncio
    async def test_guard_passthrough_runs_hooks(self) -> None:
        content = """
!auth
---
__no_spa__ = True
self.log = []

@before_load
def bl(self):
    self.log.append('before_load')
---

<p>OK</p>
"""
        page = self._make_page(content)
        page.user = ClaimsPrincipal(is_authenticated=True)

        await page.render(init=True)
        assert "before_load" in page.log

    @pytest.mark.asyncio
    async def test_guard_custom_redirect(self) -> None:
        content = """
!auth {"redirect":"/sign-in"}
---
__no_spa__ = True
---

<p>x</p>
"""
        page = self._make_page(content)
        page.user = ANONYMOUS
        response = await page.render(init=True)
        assert response.status_code == 303
        assert response.headers["location"] == "/sign-in"

    @pytest.mark.asyncio
    async def test_guard_inline_claim_denies(self) -> None:
        content = """
!auth {"claims":[["role","admin"]]}
---
__no_spa__ = True
self.log = []

@init
def i(self):
    self.log.append('ran')
---

<p>x</p>
"""
        page = self._make_page(content)
        page.user = ClaimsPrincipal(
            is_authenticated=True, claims=[Claim(type="role", value="editor")]
        )
        response = await page.render(init=True)
        assert response.status_code == 303
        assert page.log == []

    @pytest.mark.asyncio
    async def test_unprotected_page_skips_guard_entirely(self) -> None:
        """No !auth → guard code path never imports."""
        content = """
---
__no_spa__ = True
self.log = []

@before_load
def bl(self):
    self.log.append('ran')
---

<p>x</p>
"""
        page = self._make_page(content)
        # No page.user set — page still renders fine because guard is skipped.
        await page.render(init=True)
        assert page.log == ["ran"]

    @pytest.mark.asyncio
    async def test_guard_runs_on_init_false_for_spa_relocate(self) -> None:
        """Guard runs on BOTH init=True (hard load) and init=False (SPA relocate).

        The internal-relocate dispatch path in app.py uses init=False when
        rendering the target page for SPA navigation. Skipping the guard
        there (the previous behavior) let anonymous SPA navs reach pages
        that a hard reload would redirect away from. Partial in-place
        re-renders use render_update(), not render(), so this does not
        re-guard on state-driven updates.
        """
        content = """
!auth
---
__no_spa__ = True
self.log = []
---

<p>x</p>
"""
        page = self._make_page(content)
        page.user = ANONYMOUS
        response = await page.render(init=False)
        # Guard fires on relocate path and returns a redirect.
        assert response.status_code == 303

    @pytest.mark.asyncio
    async def test_guard_not_run_by_render_update(self) -> None:
        """Partial state updates go through render_update(), not render().

        render_update has no auth-guard call, so reactive writes re-render
        regions without paying the policy cost on every update.
        """
        content = """
!auth
---
__no_spa__ = True
---

<p>x</p>
"""
        page = self._make_page(content)
        page.user = ClaimsPrincipal(is_authenticated=True)
        await page.render(init=True)  # set up wire tracking
        # Revoke user, then do a partial update — must not raise or redirect.
        page.user = ANONYMOUS
        update = await page.render_update(init=False)
        assert isinstance(update, dict)


class TestResolveUser:
    def _handler(self, app: Any) -> WebSocketHandler:
        return WebSocketHandler(app)

    @pytest.mark.asyncio
    async def test_no_get_user_returns_none(self) -> None:
        app = MagicMock(spec=[])  # no get_user attribute
        h = self._handler(app)
        assert await h._resolve_user(MagicMock()) is None

    @pytest.mark.asyncio
    async def test_sync_get_user_returned_directly(self) -> None:
        app = MagicMock()
        sentinel = ClaimsPrincipal(is_authenticated=True, name="sync")
        app.get_user = MagicMock(return_value=sentinel)
        h = self._handler(app)
        result = await h._resolve_user(MagicMock())
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_async_get_user_awaited(self) -> None:
        app = MagicMock()
        sentinel = ClaimsPrincipal(is_authenticated=True, name="async")

        async def async_get_user(ws):
            return sentinel

        app.get_user = async_get_user
        h = self._handler(app)
        result = await h._resolve_user(MagicMock())
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_get_user_receives_websocket(self) -> None:
        app = MagicMock()
        ws = MagicMock()
        captured = {}

        def gu(arg):
            captured["ws"] = arg
            return None

        app.get_user = gu
        h = self._handler(app)
        await h._resolve_user(ws)
        assert captured["ws"] is ws
