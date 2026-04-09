import pytest
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from pywire.runtime.loader import PageLoader


class TestHooksRemoval:
    def setup_method(self) -> None:
        self.loader = PageLoader()
        self.temp_dir = tempfile.TemporaryDirectory()

    def teardown_method(self) -> None:
        self.temp_dir.cleanup()
        self.loader.invalidate_cache()

    def create_page_class(self, content: str, filename: str = "temp.wire") -> Any:
        path = Path(self.temp_dir.name) / filename
        path.write_text(content)
        return self.loader.load(path)

    @pytest.mark.asyncio
    async def test_standard_hooks_called_when_defined(self) -> None:
        """Verify on_load/on_before_load are called when defined by the page."""
        content = """
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

<p>Test</p>
        """
        page_class = self.create_page_class(content)
        request = MagicMock()
        # Mock app state
        request.app.state.enable_pjax = False
        request.app.state.wire._get_client_script_url.return_value = "/static/pywire.js"

        page = page_class(request, {}, {})
        page.called_hooks = []

        await page.render(init=True)

        assert "on_before_load" in page.called_hooks
        assert "on_load" in page.called_hooks
        assert "mount" in page.called_hooks

    @pytest.mark.asyncio
    async def test_standard_hooks_not_in_init_hooks_when_undefined(self) -> None:
        """Verify on_load/on_before_load are NOT in INIT_HOOKS when not defined."""
        content = """
---
@mount
def my_mount(self):
    pass
---

<p>Test</p>
        """
        page_class = self.create_page_class(content)
        assert "on_load" not in page_class.INIT_HOOKS
        assert "on_before_load" not in page_class.INIT_HOOKS
        assert "my_mount" in page_class.INIT_HOOKS
