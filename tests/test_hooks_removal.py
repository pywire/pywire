import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from pywire.runtime.loader import PageLoader


class TestHooksRemoval(unittest.TestCase):
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

    def run_async(self, coro: Any) -> Any:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_standard_hooks_ignored(self) -> None:
        """Verify on_load/on_before_load are ignored unless called manually."""
        content = """
<p>Test</p>
---
self.called_hooks = []

def on_load(self):
    self.called_hooks.append('on_load')

def on_before_load(self):
    self.called_hooks.append('on_before_load')

@mount
def my_mount(self):
    self.called_hooks.append('mount')
---
        """
        page_class = self.create_page_class(content)
        request = MagicMock()
        # Mock app state
        request.app.state.enable_pjax = False
        request.app.state.pywire._get_client_script_url.return_value = "/static/pywire.js"

        page = page_class(request, {}, {})
        page.called_hooks = []

        self.run_async(page.render(init=True))

        # 'on_load' and 'on_before_load' should NOT be present
        self.assertNotIn("on_load", page.called_hooks)
        self.assertNotIn("on_before_load", page.called_hooks)
        self.assertIn("mount", page.called_hooks)


if __name__ == "__main__":
    unittest.main()
