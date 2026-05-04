"""Tests for hot reload wire tracking survival after state migration.

Verifies that wire tracking (the mechanism that maps Wire mutations to
dirty regions for incremental re-rendering) is properly re-established
after broadcast_reload migrates state to a new page instance.

The root bug: broadcast_reload copied `slots` and `head_slots` from the
old page to the new page.  These contain bound methods referencing the old
page instance, so layout render_slot() invoked old_page's slot renderer →
wire tracking registered on old_page instead of new_page → new_page had
zero wire subscribers → render_update returned empty regions.
"""

import pytest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from pywire.compiler.codegen.generator import CodeGenerator
from pywire.compiler.parser import PyWireParser
from pywire.runtime.page import BasePage
from pywire.runtime.loader import PageLoader


COUNTER_PAGE = """\
---
count = wire(0)

def increment():
    count.value += 1

---
<div>
    <p>Count: {count.value}</p>
    <button @click={increment}>+</button>
</div>
"""


def _compile_page_class(wire_content: str) -> type:
    """Compile .wire content into a page class (no layout)."""

    parser = PyWireParser()
    generator = CodeGenerator()
    parsed = parser.parse(wire_content)
    module_ast = generator.generate(parsed)
    code_obj = compile(module_ast, "<test>", "exec")

    ns: dict = {}
    ns["BasePage"] = BasePage
    ns["__page_class__"] = None
    exec(code_obj, ns)

    page_class = ns.get("__page_class__") or next(
        v
        for v in ns.values()
        if isinstance(v, type) and issubclass(v, BasePage) and v is not BasePage
    )
    return page_class


def _make_request() -> MagicMock:
    """Create a minimal mock request."""
    req = MagicMock()
    req.url.path = "/"
    req.url = MagicMock()
    req.url.path = "/"
    req.url.__str__ = lambda self: "http://localhost/"
    req.query_params = {}
    req.scope = {"type": "http", "path": "/"}
    req.app = MagicMock()
    req.app.state = MagicMock()
    req.app.state.enable_pjax = False
    req.app.state.debug = False
    req.app.state.static_url_path = "/static"
    return req


def _create_page(page_class: type, request: Any = None) -> BasePage:
    req = request or _make_request()
    return page_class(req, {}, {})


def _simulate_migration(old_page: BasePage, new_page: BasePage) -> None:
    """Replicate the state migration logic from broadcast_reload."""
    skip_attrs = {
        "request",
        "params",
        "query",
        "path",
        "url",
        "user",
        "errors",
        "loading",
        "slots",
        "head_slots",
        "attrs",
    }
    for attr, value in old_page.__dict__.items():
        if attr not in skip_attrs and not attr.startswith("_"):
            try:
                setattr(new_page, attr, value)
            except AttributeError:
                pass
    new_page.user = old_page.user


# ---------------------------------------------------------------------------
# No-layout tests (baseline)
# ---------------------------------------------------------------------------


class TestWireTrackingNoLayout:
    """Wire tracking after hot reload migration — page without layout."""

    @pytest.mark.asyncio
    async def test_wire_tracking_survives_migration(self) -> None:
        OldClass = _compile_page_class(COUNTER_PAGE)
        NewClass = _compile_page_class(COUNTER_PAGE)
        req = _make_request()

        old_page = _create_page(OldClass, req)
        await old_page.render(init=True)

        # Increment a few times
        for _ in range(3):
            old_page.count.value += 1  # type: ignore[attr-defined]
            await old_page.render_update(init=False)

        # Migrate
        new_page = _create_page(NewClass, req)
        _simulate_migration(old_page, new_page)
        await new_page.render(init=False)

        assert len(new_page._wire_subscribers) > 0, "wire tracking not established"

        # Event after reload
        update = await new_page.handle_event("increment", {})
        assert isinstance(update, dict)
        if update["type"] == "regions":
            assert len(update["regions"]) > 0, "render_update returned empty regions"

    @pytest.mark.asyncio
    async def test_stale_handler_silently_ignored(self) -> None:
        """Missing handler should not raise after hot reload."""
        PageClass = _compile_page_class(COUNTER_PAGE)
        req = _make_request()
        page = _create_page(PageClass, req)
        await page.render(init=True)

        # Dispatch a handler that doesn't exist (stale from pre-reload DOM)
        update = await page.handle_event("nonexistent_handler", {})
        # Should return empty regions, not raise
        assert isinstance(update, dict)


# ---------------------------------------------------------------------------
# Layout tests (the actual bug scenario)
# ---------------------------------------------------------------------------

# Paths to the demo-hot-reload example that has a __layout__.wire
_DEMO_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "examples"
    / "demo-hot-reload"
    / "src"
    / "pages"
)
_INDEX_WIRE = _DEMO_DIR / "index.wire"
_LAYOUT_WIRE = _DEMO_DIR / "__layout__.wire"


@pytest.mark.skipif(
    not _INDEX_WIRE.exists() or not _LAYOUT_WIRE.exists(),
    reason="demo-hot-reload example not present",
)
class TestWireTrackingWithLayout:
    """Wire tracking after hot reload migration — page WITH layout.

    This is the scenario that triggered the original bug: slot renderers
    are bound methods, and migrating them from old_page caused wire
    tracking to register on the wrong page instance.
    """

    def _load_page_class(self) -> type:
        loader = PageLoader()
        return loader.load(_INDEX_WIRE, implicit_layout=str(_LAYOUT_WIRE.resolve()))

    @pytest.mark.asyncio
    async def test_wire_tracking_with_layout(self) -> None:
        PageClass = self._load_page_class()
        req = _make_request()

        old_page = _create_page(PageClass, req)
        await old_page.render(init=True)

        # Increment
        for _ in range(3):
            old_page.count.value += 1  # type: ignore[attr-defined]
            await old_page.render_update(init=False)

        # Hot reload: recompile and migrate
        NewPageClass = self._load_page_class()
        new_page = _create_page(NewPageClass, req)
        _simulate_migration(old_page, new_page)
        await new_page.render(init=False)

        # Critical check: wire subscribers should be on NEW page
        assert len(new_page._wire_subscribers) > 0, (
            "wire tracking not established on new page after layout render"
        )

        # Event after hot reload should produce non-empty update
        update = await new_page.handle_event("increment", {})
        assert isinstance(update, dict)
        if update["type"] == "regions":
            assert len(update["regions"]) > 0, (
                "render_update returned empty regions — wire tracking broken"
            )


# ---------------------------------------------------------------------------
# Wire reads outside any region (at the layout-body root) must still
# trigger updates on the parent page when written.
# ---------------------------------------------------------------------------


# A page with a layout where a wire is read at the BODY ROOT — outside any
# inner region. The `$if` gate means ``token_state`` is read by the body
# closure under the layout component's render context, not by an inner
# region renderer. Without the parent-bubble in ``_invalidate_wire``, the
# wire write only dirties the layout component — the page that the WS
# handler calls ``render_update`` on stays clean and the UI freezes.
ROOT_READ_LAYOUT = """\
<!DOCTYPE html>
<html><body><main>{$render children}</main></body></html>
"""

ROOT_READ_PAGE = """\
!layout "__layout__.wire"

---
token = wire("")

def issue():
    token.value = "ok"
---
<button @click={issue}>Issue</button>
<article $if={token}>
    <pre>{token}</pre>
</article>
"""


class TestParentInvalidatesOnChildWireWrite:
    """Wire writes inside a layout-component-rendered body must propagate
    to the parent page so its ``render_update`` re-renders the UI."""

    @pytest.mark.asyncio
    async def test_handler_wire_write_under_layout_dirties_parent(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "__layout__.wire").write_text(ROOT_READ_LAYOUT)
        (tmp_path / "page.wire").write_text(ROOT_READ_PAGE)
        loader = PageLoader()
        PageClass = loader.load(
            tmp_path / "page.wire",
            implicit_layout=str((tmp_path / "__layout__.wire").resolve()),
        )

        page = _create_page(PageClass)
        await page.render(init=True)

        # Click the button: handler writes to the wire. The wire was read
        # at the body root (under the layout component's context), so
        # without the bubble fix only the layout component sees the
        # invalidation and the page returns no regions / empty html.
        update = await page.handle_event("issue", {})
        assert isinstance(update, dict)
        if update.get("type") == "regions":
            assert update.get("regions"), (
                "wire write under layout body root did not dirty the parent "
                "page — UI would not update"
            )
        elif update.get("type") == "full":
            assert update.get("html"), (
                "full re-render returned empty html after wire write under "
                "layout body root"
            )
