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
    async def test_init_hooks_called_when_defined(self) -> None:
        """Verify @before_load and @init are called when defined by the page."""
        content = """
---
self.called_hooks = []

@before_load
def my_before_load(self):
    self.called_hooks.append('before_load')

@init
def my_init(self):
    self.called_hooks.append('init')
---

<p>Test</p>
        """
        page_class = self.create_page_class(content)
        request = MagicMock()
        # Mock app state
        request.app.state.enable_pjax = False
        request.app.state.interactive_server_mode = True
        request.app.state.wire._get_client_script_url.return_value = "/static/pywire.js"

        page = page_class(request, {}, {})
        page.called_hooks = []

        await page.render(init=True)

        assert "before_load" in page.called_hooks
        assert "init" in page.called_hooks

    @pytest.mark.asyncio
    async def test_hooks_not_in_init_hooks_when_undefined(self) -> None:
        """Verify hooks are NOT in INIT_HOOKS when not defined."""
        content = """
---
@init
def my_init(self):
    pass
---

<p>Test</p>
        """
        page_class = self.create_page_class(content)
        assert page_class.INIT_HOOKS == ["my_init"]
        assert page_class.BEFORE_LOAD_HOOKS == []
        assert page_class.MOUNT_HOOKS == []
