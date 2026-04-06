import pytest
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from pywire.runtime.loader import PageLoader


class TestLifecycleHooks:
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
    async def test_top_level_init_execution(self) -> None:
        """---
        Verify top-level executable statements run on init=True."""
        content = """
---
__no_spa__ = True
print("Top Level Run")
self.counter = 1
---

<p>Content</p>
        """
        page_class = self.create_page_class(content)
        request = MagicMock()
        # Mock app state for SPA injection
        request.app.state.enable_pjax = False
        request.app.state.wire._get_client_script_url.return_value = "/static/pywire.js"

        page = page_class(request, {}, {})

        # Capture stdout? Or just check side effects if possible.
        # But variable 'counter' is set on self.

        await page.render(init=True)
        assert hasattr(page, "counter")
        assert page.counter == 1

        # Verify it doesn't run on re-render
        page.counter = 99
        await page.render(init=False)
        assert page.counter == 99

    @pytest.mark.asyncio
    async def test_mount_hook(self) -> None:
        """---
        Verify @mount decorated method runs on init."""
        content = """
---
__no_spa__ = True
@mount
def initialize(self):
    self.mounted = True
---

<p>Hello</p>
        """
        page_class = self.create_page_class(content)
        request = MagicMock()
        request.app.state.enable_pjax = False
        request.app.state.wire._get_client_script_url.return_value = "/static/pywire.js"

        page = page_class(request, {}, {})

        await page.render(init=True)
        assert hasattr(page, "mounted")
        assert page.mounted is True

    @pytest.mark.asyncio
    async def test_execution_order(self) -> None:
        """---
        Verify order: top-level -> @mount."""
        content = """
---
__no_spa__ = True
if not hasattr(self, 'log'):
    self.log = []
self.log.append('top_level')

@mount
def my_mount(self):
    self.log.append('mount')
---

<p>Test</p>
        """
        page_class = self.create_page_class(content)
        request = MagicMock()
        request.app.state.enable_pjax = False
        request.app.state.wire._get_client_script_url.return_value = "/static/pywire.js"

        page = page_class(request, {}, {})

        await page.render(init=True)

        expected = ["top_level", "mount"]
        assert page.log == expected
