
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
    app.state.webtransport_cert_hash = None
    app.state.enable_pjax = False
    return app


@pytest.mark.asyncio
async def test_component_with_layout_rendering(loader: PageLoader, mock_app: MagicMock) -> None:
    """Test that a component with !layout does NOT render its layout when used as a child component."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # 1. Layout file
        layout_code = """
<div id="layout-wrapper">
    <h1>Layout Header</h1>
    <main>
        <slot />
    </main>
</div>
"""
        (tmp_path / "layout.wire").write_text(layout_code)

        # 2. Component using layout
        component_code = """
!layout "layout.wire"

<p>Component Content</p>
"""
        (tmp_path / "component.wire").write_text(component_code)

        # 3. Page using component
        page_code = """---
from component import Component
---
<div id="page-wrapper">
    <Component />
</div>
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
            assert '<div id="page-wrapper">' in html
            assert '<p>Component Content</p>' in html
            
            # The BUG: Layout wrapper SHOULD NOT be present inside component output
            assert '<div id="layout-wrapper">' not in html, "Layout wrapper unexpectedly rendered for child component!"
            assert '<h1>Layout Header</h1>' not in html

        finally:
            if tmpdir in sys.path:
                sys.path.remove(tmpdir)
            os.chdir(original_cwd)
