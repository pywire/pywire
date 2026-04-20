import sys
import unittest
from typing import Any, cast
from unittest.mock import MagicMock
import pytest

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


class TestPageRendering:
    def setup_method(self, method) -> None:
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

    def teardown_method(self, method) -> None:
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

        assert hasattr(page, "id")
        assert page.id == "42"
        assert page.slug == "test-post"

    def test_page_style_initialization(self) -> None:
        from pywire.runtime.style_collector import StyleCollector

        request = MagicMock()
        page = BasePage(request, {}, {})
        assert isinstance(page._style_collector, StyleCollector)

    def test_page_shared_style_collector(self) -> None:
        from pywire.runtime.style_collector import StyleCollector

        collector = StyleCollector()
        request = MagicMock()
        page = BasePage(request, {}, {}, _style_collector=collector)
        assert page._style_collector is collector

    @pytest.mark.asyncio
    async def test_page_injects_styles_into_head(self) -> None:
        class StylePage(BasePage):
            async def _render_template(self) -> str:
                return "<html><head></head><body></body></html>"

        request = MagicMock()
        request.app.state.enable_pjax = False
        request.app.state.debug = False
        request.app.state.interactive_server_mode = True
        page = StylePage(request, {}, {})
        page._style_collector.add("s1", ".test { color: red; }")

        # Response is a mock from self.mocks['starlette.responses'].Response
        # page.render() returns a mock response object
        await page.render()

        # The HTML is passed to the Response constructor
        from starlette.responses import Response

        html_passed = cast(Any, Response).call_args[0][0]
        assert "<style>.test { color: red; }</style></head>" in html_passed

    @pytest.mark.asyncio
    async def test_handle_event_arg_normalization(self) -> None:
        # We need Response to be available for the class definition
        from starlette.responses import Response

        class HandlerPage(BasePage):
            def on_click(self, arg0: Any = None) -> None:
                self.last_arg0 = arg0

            async def render(self, init: bool = True) -> Response:
                return Response("ok")

        request = MagicMock()
        page = HandlerPage(request, {}, {})

        # handle_event calls render() but we don't need to check its return value here
        await page.handle_event("on_click", {"args": {"arg-0": 42}})
        assert page.last_arg0 == 42


if __name__ == "__main__":
    unittest.main()
