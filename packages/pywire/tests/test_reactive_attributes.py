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
    app.state.interactive_server_mode = True
    return app


@pytest.mark.asyncio
async def test_variable_binding(loader: PageLoader, mock_app: MagicMock) -> None:
    """---
    Test attr={var} binding."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        page_code = """
---
my_id = "dynamic-id"
my_class = "btn"
---

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
            html = await page._render_template()

            assert 'id="dynamic-id"' in html
            assert 'class="btn"' in html
        finally:
            os.chdir(orig_cwd)


@pytest.mark.asyncio
async def test_method_binding_paramless(
    loader: PageLoader, mock_app: MagicMock
) -> None:
    """---
    Test attr="method" auto-call binding."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        page_code = """
---
def get_title():
    return "My Title"
---

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
            html = await page._render_template()

            assert 'title="My Title"' in html
        finally:
            os.chdir(orig_cwd)


@pytest.mark.asyncio
async def test_expression_binding(loader: PageLoader, mock_app: MagicMock) -> None:
    """---
    Test attr={expr} binding."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        page_code = """
---
is_error = True
---

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
            html = await page._render_template()

            assert 'class="error"' in html
        finally:
            os.chdir(orig_cwd)


@pytest.mark.asyncio
async def test_boolean_attributes(loader: PageLoader, mock_app: MagicMock) -> None:
    """---
    Test boolean attribute behavior."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        page_code = """
---
is_checked = True
is_disabled = False
is_readonly = None
---

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
            html = await page._render_template()

            # checked="True" -> checked=""
            assert 'checked=""' in html
            # disabled="False" -> omitted
            assert "disabled" not in html
            # readonly="None" -> omitted
            assert "readonly" not in html
        finally:
            os.chdir(orig_cwd)


@pytest.mark.asyncio
async def test_async_binding(loader: PageLoader, mock_app: MagicMock) -> None:
    """---
    Test attr={await async_call()} binding."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        page_code = """
---
async def get_data():
    return "async-data"
---

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
            html = await page._render_template()

            assert 'data-val="async-data"' in html
        finally:
            os.chdir(orig_cwd)


@pytest.mark.asyncio
async def test_aria_boolean_attributes(loader: PageLoader, mock_app: MagicMock) -> None:
    """---
    Test ARIA boolean attributes (true/false strings)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        page_code = """
---
is_loading = True
is_expanded = False
---

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
            html = await page._render_template()

            # aria-busy="true"
            assert 'aria-busy="true"' in html
            # aria-expanded="false"
            assert 'aria-expanded="false"' in html
        finally:
            os.chdir(orig_cwd)


@pytest.mark.asyncio
async def test_reactive_attributes_wire_and_dot_value(
    loader: PageLoader, mock_app: MagicMock
) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        page_code = """
---
title_wire = wire("A")
disabled_wire = wire(False)

def toggle():
    self.disabled_wire.value = not self.disabled_wire.value
    self.title_wire.value = "B"
---

<button title={title_wire} aria-label={title_wire.value} disabled={disabled_wire.value} @click={toggle}>x</button>
"""
        (tmp_path / "page.wire").write_text(page_code)

        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            page_class = loader.load(tmp_path / "page.wire")
            request = MagicMock()
            request.app = mock_app
            page = page_class(request, {}, {}, {}, None)

            initial = await page.render(init=True)
            html = initial.body.decode()
            assert 'title="A"' in html
            assert 'aria-label="A"' in html
            assert "disabled" not in html

            update = await page.handle_event("toggle", {})

            if update["type"] == "full":
                assert 'title="B"' in update["html"]
                assert 'aria-label="B"' in update["html"]
                assert "disabled" in update["html"]
                return
            joined = " ".join(region["html"] for region in update["regions"])
            assert 'title="B"' in joined
            assert 'aria-label="B"' in joined
            assert "disabled" in joined
        finally:
            os.chdir(orig_cwd)
