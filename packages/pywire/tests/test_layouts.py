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
    from unittest.mock import MagicMock

    app = MagicMock()
    app.state = MagicMock()
    app.state.webtransport_cert_hash = None
    app.state.enable_pjax = False
    return app


def test_simple_layout(loader: PageLoader, mock_app: MagicMock) -> None:
    """Test basic layout with default and named slots."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create layout with slots
        layout_code = """
<div id="layout">
    <slot name="header">Default Header</slot>
    <main>
        <slot />
    </main>
    <footer>
        <slot name="footer">Default Footer</slot>
    </footer>
</div>
"""
        (tmp_path / "layout.pywire").write_text(layout_code)

        # Create page - using <slot name="..."> to fill slots
        page_code = """
!layout "layout.pywire"

<h1>Page Content</h1>
<p>More content</p>

<slot name="header">
    <div>Custom Header</div>
</slot>
"""
        (tmp_path / "page.pywire").write_text(page_code)

        original_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            page_class = loader.load(tmp_path / "page.pywire")
            assert issubclass(page_class, BasePage)

            request = MagicMock()
            request.app = mock_app
            page = page_class(request, {}, {}, {}, None)
            html = asyncio.run(page._render_template())

            assert '<div id="layout">' in html
            assert "Custom Header" in html
            assert "Default Header" not in html
            assert "Default Footer" in html
            assert "<h1>Page Content</h1>" in html

        finally:
            os.chdir(original_cwd)


def test_head_slot_accumulation(loader: PageLoader, mock_app: MagicMock) -> None:
    """Test that <head> content from child pages is appended to $head slot."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Root layout with $head slot
        root_layout = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <slot $head />
</head>
<body>
    <slot />
</body>
</html>
"""
        (tmp_path / "root.pywire").write_text(root_layout)

        # Child layout - uses <head> to append to $head slot
        child_layout = """
!layout "root.pywire"

<head>
    <link rel="stylesheet" href="/styles.css">
</head>

<main class="container">
    <slot />
</main>
"""
        (tmp_path / "child.pywire").write_text(child_layout)

        # Page - uses <head> to append to $head slot
        page_code = """
!layout "child.pywire"

<head>
    <title>My Page</title>
</head>

<h1>Page Content</h1>
"""
        (tmp_path / "page.pywire").write_text(page_code)

        original_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            page_class = loader.load(tmp_path / "page.pywire")
            request = MagicMock()
            request.app = mock_app
            page = page_class(request, {}, {}, {}, None)
            html = asyncio.run(page._render_template())

            # Verify head content is accumulated
            assert '<meta charset="utf-8">' in html
            assert 'href="/styles.css"' in html
            assert "My Page</title>" in html

            # Verify order: meta (root) before link (child) before title (page)
            meta_pos = html.find('<meta charset="utf-8">')
            link_pos = html.find("<link")
            title_pos = html.find("</title>")
            assert meta_pos < link_pos < title_pos, (
                f"Order wrong: meta={meta_pos}, link={link_pos}, title={title_pos}"
            )

        finally:
            os.chdir(original_cwd)
