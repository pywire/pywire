"""Layout-as-component integration tests (Phase 7 — red before Phase 8).

These tests exercise the target end-state where a ``!layout`` directive
just wraps the page as a regular component receiving the implicit
``children`` snippet prop, and where ``{$head}...{/head}`` blocks
teleport to the document head through the hierarchical layout chain.

They are expected to go green when Phase 8 (layout collapse) lands.
"""

from __future__ import annotations

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
async def test_three_level_layout_chain_with_children_snippet(
    loader: PageLoader, mock_app: MagicMock
) -> None:
    """Root → child → page; each level uses ``{$render children}``."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        (tmp_path / "root.wire").write_text(
            """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
</head>
<body>
  <div id="root">{$render children}</div>
</body>
</html>
"""
        )
        (tmp_path / "child.wire").write_text(
            """
!layout "root.wire"

<main class="container">
  {$render children}
</main>
"""
        )
        (tmp_path / "page.wire").write_text(
            """
!layout "child.wire"

<h1>Page Content</h1>
"""
        )

        original_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            page_class = loader.load(tmp_path / "page.wire")
            request = MagicMock()
            request.app = mock_app
            page = page_class(request, {}, {}, {}, None)
            html = await page._render_and_cleanup()

            assert 'id="root"' in html
            assert 'class="container"' in html
            assert "<h1>Page Content</h1>" in html
            # Correct nesting: root wraps child wraps page
            root_pos = html.find('id="root"')
            main_pos = html.find('class="container"')
            h1_pos = html.find("<h1>Page Content</h1>")
            assert root_pos < main_pos < h1_pos
        finally:
            os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_head_teleport_accumulates_through_layout_chain(
    loader: PageLoader, mock_app: MagicMock
) -> None:
    """``{$head}`` blocks at every level append to document head."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        (tmp_path / "root.wire").write_text(
            """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
</head>
<body>
  {$render children}
</body>
</html>
"""
        )
        (tmp_path / "child.wire").write_text(
            """
!layout "root.wire"

{$head}
  <link rel="stylesheet" href="/styles.css">
{/head}

<main>{$render children}</main>
"""
        )
        (tmp_path / "page.wire").write_text(
            """
!layout "child.wire"

{$head}
  <title>My Page</title>
{/head}

<h1>Page Content</h1>
"""
        )

        original_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            page_class = loader.load(tmp_path / "page.wire")
            request = MagicMock()
            request.app = mock_app
            page = page_class(request, {}, {}, {}, None)
            html = await page._render_and_cleanup()

            assert '<meta charset="utf-8">' in html
            assert 'href="/styles.css"' in html
            assert "<title>My Page</title>" in html

            # meta is in root layout; link comes from child via teleport;
            # title from page via teleport. Teleports land in <head>.
            meta_pos = html.find('<meta charset="utf-8">')
            link_pos = html.find("<link")
            title_pos = html.find("<title>")
            body_pos = html.find("<body>")
            # All three live in the document <head>, which precedes <body>.
            assert meta_pos < body_pos
            assert link_pos < body_pos
            assert title_pos < body_pos
        finally:
            os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_last_title_wins_across_chain(
    loader: PageLoader, mock_app: MagicMock
) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        (tmp_path / "layout.wire").write_text(
            """
<!DOCTYPE html>
<html>
<head></head>
<body>{$render children}</body>
</html>
"""
        )
        (tmp_path / "page.wire").write_text(
            """
!layout "layout.wire"

{$head}<title>Layout</title>{/head}
{$head}<title>Page</title>{/head}

<p>hi</p>
"""
        )

        original_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            page_class = loader.load(tmp_path / "page.wire")
            request = MagicMock()
            request.app = mock_app
            page = page_class(request, {}, {}, {}, None)
            html = await page._render_and_cleanup()
            # Only the latest title survives the HeadBuffer flush.
            assert html.count("<title>") == 1
            assert "<title>Page</title>" in html
            assert "<title>Layout</title>" not in html
        finally:
            os.chdir(original_cwd)
