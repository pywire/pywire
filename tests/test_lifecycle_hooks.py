import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any, Coroutine
from unittest.mock import MagicMock

from pywire.runtime.loader import PageLoader


class TestLifecycleHooks(unittest.TestCase):
    def setUp(self) -> None:
        self.loader = PageLoader()
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        self.loader.invalidate_cache()

    def create_page_class(self, content: str, filename: str = "temp.pywire") -> Any:
        path = Path(self.temp_dir.name) / filename
        path.write_text(content)
        return self.loader.load(path)

    def run_async(self, coro: Coroutine[Any, Any, Any]) -> Any:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_top_level_init_execution(self) -> None:
        """Verify top-level executable statements run on init=True."""
        content = """
<p>Content</p>
---
print("Top Level Run")
self.counter = 1
---
        """
        page_class = self.create_page_class(content)
        request = MagicMock()
        # Mock app state for SPA injection
        request.app.state.enable_pjax = False
        request.app.state.pywire._get_client_script_url.return_value = "/static/pywire.js"

        page = page_class(request, {}, {})

        # Capture stdout? Or just check side effects if possible.
        # But variable 'counter' is set on self.

        self.run_async(page.render(init=True))
        self.assertTrue(hasattr(page, "counter"))
        self.assertEqual(page.counter, 1)

        # Verify it doesn't run on re-render
        page.counter = 99
        self.run_async(page.render(init=False))
        self.assertEqual(page.counter, 99)

    def test_mount_hook(self) -> None:
        """Verify @mount decorated method runs on init."""
        content = """
<p>Hello</p>
---
@mount
def initialize(self):
    self.mounted = True
---
        """
        page_class = self.create_page_class(content)
        request = MagicMock()
        request.app.state.enable_pjax = False
        request.app.state.pywire._get_client_script_url.return_value = "/static/pywire.js"

        page = page_class(request, {}, {})

        self.run_async(page.render(init=True))
        self.assertTrue(hasattr(page, "mounted"))
        self.assertTrue(page.mounted)

    def test_execution_order(self) -> None:
        """Verify order: top-level -> @mount."""
        content = """
<p>Test</p>
---
self.log.append('top_level')

@mount
def my_mount(self):
    self.log.append('mount')
---
        """
        page_class = self.create_page_class(content)
        request = MagicMock()
        request.app.state.enable_pjax = False
        request.app.state.pywire._get_client_script_url.return_value = "/static/pywire.js"

        page = page_class(request, {}, {})
        page.log = []

        self.run_async(page.render(init=True))

        expected = ["top_level", "mount"]
        self.assertEqual(page.log, expected)


if __name__ == "__main__":
    unittest.main()
