import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from pywire.runtime.loader import PageLoader

@pytest.fixture
def loader() -> PageLoader:
    return PageLoader()

@pytest.fixture
def mock_app() -> MagicMock:
    app = MagicMock()
    app.state = MagicMock()
    app.state.webtransport_cert_hash = None
    app.state.enable_pjax = False
    return app

@pytest.mark.asyncio
async def test_bug_event_inline(loader: PageLoader, mock_app: MagicMock) -> None:
    """Repro: event object not available in inline handlers."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        page_code = """
---
last_key = ""
def handle_click(event):
    global last_key
    last_key = event.key
---
<button @click={self.last_key = event.key}>Click</button>
"""
        (tmp_path / "page.wire").write_text(page_code)
        
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            page_class = loader.load(tmp_path / "page.wire")
            request = MagicMock()
            request.app = mock_app
            page = page_class(request, {}, {}, {}, None)
            
            # Find the generated handler name (likely _handler_0)
            handler_name = "_handler_0"
            event_data = {"type": "click", "key": "Enter", "id": "btn1"}
            
            # This should not raise TypeError: _handler_0() got an unexpected keyword argument 'event'
            await page.handle_event(handler_name, event_data)
            assert page.last_key == "Enter"
        finally:
            os.chdir(orig_cwd)

@pytest.mark.asyncio
async def test_bug_wire_reactivity_if(loader: PageLoader, mock_app: MagicMock) -> None:
    """Repro: wire vars in $if don't trigger reactivity because wire_vars is missing in codegen."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        page_code = """
---
from pywire.core.wire import wire
count = wire(0)
---
<div>
    {$if count > 0}
        <span>Positive</span>
    {$else}
        <span>Zero</span>
    {/if}
</div>
"""
        (tmp_path / "page.wire").write_text(page_code)
        
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            page_class = loader.load(tmp_path / "page.wire")
            request = MagicMock()
            request.app = mock_app
            page = page_class(request, {}, {}, {}, None)
            
            # First render - should track 'count'
            html = await page._render_template()
            assert "Zero" in html
            
            # Verify 'count' is tracked
            assert (page.count, "value") in page._wire_subscribers
            
            # Change count and verify invalidate_wire is called
            page._invalidate_wire = MagicMock()
            page.count.value = 1
            assert page._invalidate_wire.called
        finally:
            os.chdir(orig_cwd)

@pytest.mark.asyncio
async def test_bug_builtins_inline(loader: PageLoader, mock_app: MagicMock) -> None:
    """Repro: built-in functions fail in inline handlers."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        # We'll use print() and min()
        page_code = """
---
val = 0
---
<button @click={self.val = min(10, 20); print("Clicked")}>Click</button>
"""
        (tmp_path / "page.wire").write_text(page_code)
        
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            page_class = loader.load(tmp_path / "page.wire")
            request = MagicMock()
            request.app = mock_app
            page = page_class(request, {}, {}, {}, None)
            
            handler_name = "_handler_0"
            # This should not fail with NameError: name 'min' is not defined (or being lifted as arg0)
            await page.handle_event(handler_name, {"type": "click"})
            assert page.val == 10
        finally:
            os.chdir(orig_cwd)
