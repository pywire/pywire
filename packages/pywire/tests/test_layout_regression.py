
import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pywire.runtime.loader import PageLoader
from pywire.runtime.page import BasePage


@pytest.fixture
def loader() -> PageLoader:
    return PageLoader()


@pytest.fixture
def mock_app() -> MagicMock:
    app = MagicMock()
    app.state = MagicMock()
    return app


@pytest.mark.asyncio
async def test_component_with_layout_no_content_regression(loader: PageLoader, mock_app: MagicMock) -> None:
    """Test that a component with !layout but NO content (or empty default slot) does not crash."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # 1. Layout file
        layout_code = """
<div id="layout-wrapper">
    <slot />
</div>
"""
        (tmp_path / "__layout__.wire").write_text(layout_code)

        # 2. Component using layout but ONLY Python code (no template)
        # This causes 'default' slot to be strictly empty.
        component_code = """---
x = 1
---
"""
        (tmp_path / "component.wire").write_text(component_code)

        # 3. Page using component
        page_code = """---
from component import Component
---
<Component />
"""
        (tmp_path / "page.wire").write_text(page_code)

        original_cwd = os.getcwd()
        os.chdir(tmpdir)
        import sys
        from pywire.runtime.importer import install_import_hook
        install_import_hook()
        if tmpdir not in sys.path:
            sys.path.insert(0, tmpdir)
        
        try:
            # Load and render the page
            page_class = loader.load(tmp_path / "page.wire", use_cache=False)
            request = MagicMock()
            request.app = mock_app
            page = page_class(request, {}, {}, {}, None)
            
            # Helper to run async render
            async def run_render():
                response = await page.render()
                return response.body.decode()

            html = await run_render()

            print(f"DEBUG: Rendered HTML: {html}")

            # Assertions
            # 1. Should NOT crash (AttributeError regression)
            # 2. Should NOT contain layout wrapper (Layout duplication fix)
            assert '<div id="layout-wrapper">' not in html, "Layout wrapper unexpectedly rendered!"
            
            # 3. Should contain base page scripts (verifying successful render)
            assert '<script id="_pywire_spa_meta"' in html

        finally:
            if tmpdir in sys.path:
                sys.path.remove(tmpdir)
            os.chdir(original_cwd)
