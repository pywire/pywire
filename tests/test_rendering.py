import asyncio
import sys
import unittest
from typing import Any, cast
from unittest.mock import MagicMock

BasePage: Any = None


# Helper to mock modules for tests
def mock_modules(mapping: dict) -> dict:
    original_modules = {}
    for name, mock in mapping.items():
        if name in sys.modules:
            original_modules[name] = sys.modules[name]
        sys.modules[name] = mock
    return original_modules


def restore_modules(original_modules: dict, mapping: dict) -> None:
    for name in mapping:
        if name in original_modules:
            sys.modules[name] = original_modules[name]
        else:
            del sys.modules[name]


class TestPageRendering(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_starlette = MagicMock()
        self.mocks = {
            "starlette": self.mock_starlette,
            "starlette.requests": self.mock_starlette,
            "starlette.responses": self.mock_starlette,
            "starlette.routing": self.mock_starlette,
            "starlette.staticfiles": self.mock_starlette,
            "starlette.applications": self.mock_starlette,
            "starlette.websockets": self.mock_starlette,
            "starlette.datastructures": self.mock_starlette,
            "starlette.types": self.mock_starlette,
            "starlette.exceptions": self.mock_starlette,
            "starlette.middleware": self.mock_starlette,
            "jinja2": MagicMock(),
            "lxml": MagicMock(),
            "lxml.html": MagicMock(),
            "lxml.etree": MagicMock(),
        }
        self.original_modules = mock_modules(self.mocks)

        # Import BasePage after mocking
        global BasePage
        import importlib

        import pywire.runtime.loader as loader_mod
        import pywire.runtime.page as page_mod

        importlib.reload(page_mod)
        importlib.reload(loader_mod)
        BasePage = page_mod.BasePage

    def tearDown(self) -> None:
        import importlib

        import pywire.runtime.loader as loader_mod
        import pywire.runtime.page as page_mod

        restore_modules(self.original_modules, self.mocks)
        importlib.reload(page_mod)
        importlib.reload(loader_mod)

    def test_params_as_attributes(self) -> None:
        """Verify params are exposed as attributes."""
        request = MagicMock()
        params = {"id": "42", "slug": "test-post"}

        page = BasePage(request, params=params, query={})

        self.assertTrue(hasattr(page, "id"))
        self.assertEqual(page.id, "42")
        self.assertEqual(page.slug, "test-post")

    def test_recursive_slot_logic(self) -> None:
        """Verify slot registration logic manually."""

        # 1. Root Layout (LAYOUT_ID="ROOT")
        class RootLayout(BasePage):
            LAYOUT_ID = "ROOT"

            async def _render_template(self) -> str:
                # <slot /> renders default slot for layout ROOT
                renderer = self.slots.get("ROOT", {}).get("default")
                content = await renderer() if renderer else ""
                return "ROOT_START|" + content + "|ROOT_END"

            def _init_slots(self) -> None:
                if hasattr(super(), "_init_slots"):
                    super()._init_slots()

        # 2. Sub Layout (LAYOUT_ID="SUB", parent="ROOT")
        class SubLayout(RootLayout):
            LAYOUT_ID = "SUB"

            # CodeGen: registers filler for ROOT default slot
            # MUST be unique to avoid override by child!
            async def _render_slot_fill_default_sub(self) -> str:
                # SubLayout content: <slot /> (which renders SUB default slot)
                renderer = self.slots.get("SUB", {}).get("default")
                content = await renderer() if renderer else ""
                return "SUB_START|" + content + "|SUB_END"

            def _init_slots(self) -> None:
                if hasattr(super(), "_init_slots"):
                    super()._init_slots()
                # Register self for parent
                self.register_slot("ROOT", "default", self._render_slot_fill_default_sub)

        # 3. Leaf Page (parent="SUB")
        class LeafPage(SubLayout):
            # NO LAYOUT_ID (it's a page)

            # CodeGen: registers filler for SUB default slot
            async def _render_slot_fill_default_leaf(self) -> str:
                return "LEAF_CONTENT"

            def _init_slots(self) -> None:
                if hasattr(super(), "_init_slots"):
                    super()._init_slots()
                self.register_slot("SUB", "default", self._render_slot_fill_default_leaf)

        # Execution
        request = MagicMock()
        page = LeafPage(request, params={}, query={})

        # Generated code would call this in __init__
        page._init_slots()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # BasePage.render() calls self._render_template().
            content = loop.run_until_complete(page._render_template())
            self.assertEqual(content, "ROOT_START|SUB_START|LEAF_CONTENT|SUB_END|ROOT_END")
        finally:
            loop.close()

    def test_page_style_initialization(self) -> None:
        from pywire.runtime.style_collector import StyleCollector

        request = MagicMock()
        page = BasePage(request, {}, {})
        self.assertIsInstance(page._style_collector, StyleCollector)

    def test_page_shared_style_collector(self) -> None:
        from pywire.runtime.style_collector import StyleCollector

        collector = StyleCollector()
        request = MagicMock()
        page = BasePage(request, {}, {}, _style_collector=collector)
        self.assertIs(page._style_collector, collector)

    def test_page_injects_styles_into_head(self) -> None:
        class StylePage(BasePage):
            async def _render_template(self) -> str:
                return "<html><head></head><body></body></html>"

        request = MagicMock()
        page = StylePage(request, {}, {})
        page._style_collector.add("s1", ".test { color: red; }")

        loop = asyncio.new_event_loop()
        try:
            # Response is a mock from self.mocks['starlette.responses'].Response
            # page.render() returns a mock response object
            loop.run_until_complete(page.render())

            # The HTML is passed to the Response constructor
            from starlette.responses import Response

            html_passed = cast(Any, Response).call_args[0][0]
            self.assertIn("<style>.test { color: red; }</style></head>", html_passed)
        finally:
            loop.close()

    def test_render_head_slot_append(self) -> None:
        request = MagicMock()
        page = BasePage(request, {}, {})
        page.register_head_slot("main", lambda: "<meta 1>")
        page.register_head_slot("main", lambda: "<meta 2>")

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                page.render_slot("$head", layout_id="main", append=True)
            )
            self.assertIn("<meta 1>", result)
            self.assertIn("<meta 2>", result)
        finally:
            loop.close()

    def test_handle_event_arg_normalization(self) -> None:
        # We need Response to be available for the class definition
        from starlette.responses import Response

        class HandlerPage(BasePage):
            def on_click(self, arg0: Any = None) -> None:
                self.last_arg0 = arg0

            async def render(self, init: bool = True) -> Response:
                return Response("ok")

        request = MagicMock()
        page = HandlerPage(request, {}, {})

        loop = asyncio.new_event_loop()
        try:
            # handle_event calls render() but we don't need to check its return value here
            loop.run_until_complete(page.handle_event("on_click", {"args": {"arg-0": 42}}))
            self.assertEqual(page.last_arg0, 42)
        finally:
            loop.close()


if __name__ == "__main__":
    unittest.main()
