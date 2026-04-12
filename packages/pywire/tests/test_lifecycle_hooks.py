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
        """Verify top-level executable statements run on init=True."""
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
        request.app.state.enable_pjax = False
        request.app.state.wire._get_client_script_url.return_value = "/static/pywire.js"

        page = page_class(request, {}, {})

        await page.render(init=True)
        assert hasattr(page, "counter")
        assert page.counter == 1

        # Verify it doesn't run on re-render
        page.counter = 99
        await page.render(init=False)
        assert page.counter == 99

    @pytest.mark.asyncio
    async def test_init_hook(self) -> None:
        """Verify @init decorated method runs on init."""
        content = """
---
__no_spa__ = True
@init
def initialize(self):
    self.initialized = True
---

<p>Hello</p>
        """
        page_class = self.create_page_class(content)
        request = MagicMock()
        request.app.state.enable_pjax = False
        request.app.state.wire._get_client_script_url.return_value = "/static/pywire.js"

        page = page_class(request, {}, {})

        await page.render(init=True)
        assert hasattr(page, "initialized")
        assert page.initialized is True

    @pytest.mark.asyncio
    async def test_execution_order(self) -> None:
        """Verify order: top-level (init) -> @before_load -> @init.
        Top-level runs during __init__, @before_load and @init run during render(init=True)."""
        content = """
---
__no_spa__ = True
if not hasattr(self, 'log'):
    self.log = []
self.log.append('top_level')

@before_load
def my_before_load(self):
    self.log.append('before_load')

@init
def my_init(self):
    self.log.append('init')
---

<p>Test</p>
        """
        page_class = self.create_page_class(content)
        request = MagicMock()
        request.app.state.enable_pjax = False
        request.app.state.wire._get_client_script_url.return_value = "/static/pywire.js"

        page = page_class(request, {}, {})

        await page.render(init=True)

        # top_level runs during __init__, before_load and init run during render
        expected = ["top_level", "before_load", "init"]
        assert page.log == expected

    @pytest.mark.asyncio
    async def test_before_update_can_cancel(self) -> None:
        """Verify @before_update returning False skips update."""
        content = """
---
__no_spa__ = True
self.counter = 0
self.allow_update = True

@before_update
def guard(self):
    return self.allow_update

def increment(self):
    self.counter += 1
---

<p>{counter}</p>
        """
        page_class = self.create_page_class(content)
        request = MagicMock()
        request.app.state.enable_pjax = False
        request.app.state.wire._get_client_script_url.return_value = "/static/pywire.js"

        page = page_class(request, {}, {})
        await page.render(init=True)

        # Normal update should work
        result = await page.handle_event("increment", {})
        assert page.counter == 1

        # Block updates
        page.allow_update = False
        result = await page.handle_event("increment", {})
        assert result == {"type": "regions", "regions": []}
        assert page.counter == 2  # handler still ran, but update was skipped

    @pytest.mark.asyncio
    async def test_error_hook_suppresses(self) -> None:
        """Verify @error hook can suppress exceptions."""
        content = """
---
__no_spa__ = True
self.error_caught = None

@error
def handle_error(self, exc):
    self.error_caught = str(exc)
    return True  # Suppress

def fail(self):
    raise ValueError("test error")
---

<p>Test</p>
        """
        page_class = self.create_page_class(content)
        request = MagicMock()
        request.app.state.enable_pjax = False
        request.app.state.wire._get_client_script_url.return_value = "/static/pywire.js"

        page = page_class(request, {}, {})
        await page.render(init=True)

        # Error should be suppressed, not raised
        await page.handle_event("fail", {})
        assert page.error_caught == "test error"

    @pytest.mark.asyncio
    async def test_error_hook_does_not_suppress(self) -> None:
        """Verify @error hook that returns falsy allows exception to propagate."""
        content = """
---
__no_spa__ = True
self.error_caught = None

@error
def handle_error(self, exc):
    self.error_caught = str(exc)
    return False  # Don't suppress

def fail(self):
    raise ValueError("test error")
---

<p>Test</p>
        """
        page_class = self.create_page_class(content)
        request = MagicMock()
        request.app.state.enable_pjax = False
        request.app.state.wire._get_client_script_url.return_value = "/static/pywire.js"

        page = page_class(request, {}, {})
        await page.render(init=True)

        with pytest.raises(ValueError, match="test error"):
            await page.handle_event("fail", {})
        assert page.error_caught == "test error"

    def test_hook_class_attributes(self) -> None:
        """Verify all hook lists are correctly generated as class attributes."""
        content = """
---
__no_spa__ = True

@before_load
def bl(self):
    pass

@init
def i(self):
    pass

@mount
def m(self):
    pass

@unmount
def um(self):
    pass

@before_update
def bu(self):
    pass

@after_update
def au(self):
    pass

@error
def e(self, exc):
    pass
---

<p>Test</p>
        """
        page_class = self.create_page_class(content)
        assert page_class.BEFORE_LOAD_HOOKS == ["bl"]
        assert page_class.INIT_HOOKS == ["i"]
        assert page_class.MOUNT_HOOKS == ["m"]
        assert page_class.UNMOUNT_HOOKS == ["um"]
        assert page_class.BEFORE_UPDATE_HOOKS == ["bu"]
        assert page_class.AFTER_UPDATE_HOOKS == ["au"]
        assert page_class.ERROR_HOOKS == ["e"]
