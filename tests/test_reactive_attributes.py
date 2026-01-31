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
    from unittest.mock import MagicMock

    app = MagicMock()
    app.state = MagicMock()
    app.state.webtransport_cert_hash = None
    app.state.enable_pjax = False
    return app


def test_variable_binding(loader: PageLoader, mock_app: MagicMock) -> None:
    """Test attr={var} binding."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        page_code = """
my_id = "dynamic-id"
my_class = "btn"
---html---
<div id={my_id} class={my_class}></div>
"""
        (tmp_path / "page.wire").write_text(page_code)

        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            page_class = loader.load(tmp_path / "page.wire")
            request = MagicMock()
            request.app = mock_app
            page = page_class(request, {}, {}, {}, None)
            html = asyncio.run(page._render_template())

            assert 'id="dynamic-id"' in html
            assert 'class="btn"' in html
        finally:
            os.chdir(orig_cwd)


def test_method_binding_paramless(loader: PageLoader, mock_app: MagicMock) -> None:
    """Test attr="method" auto-call binding."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        page_code = """
def get_title():
    return "My Title"
---html---
<div title={get_title}></div>
"""
        (tmp_path / "page.wire").write_text(page_code)

        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            page_class = loader.load(tmp_path / "page.wire")
            request = MagicMock()
            request.app = mock_app
            page = page_class(request, {}, {}, {}, None)
            html = asyncio.run(page._render_template())

            assert 'title="My Title"' in html
        finally:
            os.chdir(orig_cwd)


def test_expression_binding(loader: PageLoader, mock_app: MagicMock) -> None:
    """Test attr={expr} binding."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        page_code = """
is_error = True
---html---
<div class={"error" if is_error else "success"}></div>
"""
        (tmp_path / "page.wire").write_text(page_code)

        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            page_class = loader.load(tmp_path / "page.wire")
            request = MagicMock()
            request.app = mock_app
            page = page_class(request, {}, {}, {}, None)
            html = asyncio.run(page._render_template())

            assert 'class="error"' in html
        finally:
            os.chdir(orig_cwd)


def test_boolean_attributes(loader: PageLoader, mock_app: MagicMock) -> None:
    """Test boolean attribute behavior."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        page_code = """
is_checked = True
is_disabled = False
is_readonly = None
---html---
<input type="checkbox" checked={is_checked} disabled={is_disabled} readonly={is_readonly}>
"""
        (tmp_path / "page.wire").write_text(page_code)

        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            page_class = loader.load(tmp_path / "page.wire")
            request = MagicMock()
            request.app = mock_app
            page = page_class(request, {}, {}, {}, None)
            html = asyncio.run(page._render_template())

            # checked="True" -> checked=""
            assert 'checked=""' in html
            # disabled="False" -> omitted
            assert "disabled" not in html
            # readonly="None" -> omitted
            assert "readonly" not in html
        finally:
            os.chdir(orig_cwd)


def test_async_binding(loader: PageLoader, mock_app: MagicMock) -> None:
    """Test attr={await async_call()} binding."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        page_code = """
async def get_data():
    return "async-data"
---html---
<div data-val={await get_data()}></div>
"""
        (tmp_path / "page.wire").write_text(page_code)

        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            page_class = loader.load(tmp_path / "page.wire")
            request = MagicMock()
            request.app = mock_app
            page = page_class(request, {}, {}, {}, None)
            html = asyncio.run(page._render_template())

            assert 'data-val="async-data"' in html
        finally:
            os.chdir(orig_cwd)


def test_aria_boolean_attributes(loader: PageLoader, mock_app: MagicMock) -> None:
    """Test ARIA boolean attributes (true/false strings)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        page_code = """
is_loading = True
is_expanded = False
---html---
<div aria-busy={is_loading} aria-expanded={is_expanded}></div>
"""
        (tmp_path / "page.wire").write_text(page_code)

        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            page_class = loader.load(tmp_path / "page.wire")
            request = MagicMock()
            request.app = mock_app
            page = page_class(request, {}, {}, {}, None)
            html = asyncio.run(page._render_template())

            # aria-busy="true"
            assert 'aria-busy="true"' in html
            # aria-expanded="false"
            assert 'aria-expanded="false"' in html
        finally:
            os.chdir(orig_cwd)
