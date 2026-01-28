from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pywire.compiler.exceptions import PyWireSyntaxError
from pywire.runtime.compile_error_page import CompileErrorPage
from starlette.requests import Request
from starlette.responses import HTMLResponse


@pytest.fixture
def mock_request() -> MagicMock:
    request = MagicMock(spec=Request)
    request.scope = {"type": "http", "server": ("localhost", 8000), "path": "/"}
    return request


@pytest.fixture
def temp_pywire_file(tmp_path: Path) -> str:
    file_path = tmp_path / "test.pywire"
    content = "\n".join([f"line {i}" for i in range(1, 20)])
    file_path.write_text(content)
    return str(file_path)


@pytest.mark.asyncio
async def test_compile_error_page_syntax_error(
    mock_request: MagicMock, temp_pywire_file: str
) -> None:
    error = PyWireSyntaxError("Invalid syntax", file_path=temp_pywire_file, line=10)
    page = CompileErrorPage(mock_request, error)

    response = await page.render()
    assert isinstance(response, HTMLResponse)
    assert response.status_code == 200
    content = bytes(response.body).decode()
    assert "PyWire Syntax Error" in content
    assert "Invalid syntax" in content
    assert "line 10" in content
    assert "line-num'>10</span>" in content
    assert "line-current" in content
    assert temp_pywire_file in content


@pytest.mark.asyncio
async def test_compile_error_page_generic_exception(
    mock_request: MagicMock, temp_pywire_file: str
) -> None:
    try:
        # Create an exception with a traceback
        raise ValueError("Something went wrong")
    except Exception as e:
        error = e

    page = CompileErrorPage(mock_request, error, file_path=temp_pywire_file)

    response = await page.render()
    content = bytes(response.body).decode()

    assert "Compilation Error" in content
    assert "ValueError: Something went wrong" in content
    assert "Full Traceback" in content
    assert "ValueError" in content


@pytest.mark.asyncio
async def test_compile_error_page_traceback_inference(
    mock_request: MagicMock, tmp_path: Path
) -> None:
    # Create a dummy file and raise an error that "looks" like it came from there
    file_path = tmp_path / "app_logic.pywire"
    file_path.write_text("dummy content")

    def raise_err() -> None:
        raise RuntimeError("Fail")

    try:
        raise_err()
    except Exception as e:
        error = e

    page = CompileErrorPage(mock_request, error)

    response = await page.render()
    content = bytes(response.body).decode()

    assert "RuntimeError: Fail" in content
    assert "Full Traceback" in content


@pytest.mark.asyncio
async def test_compile_error_page_missing_file(mock_request: MagicMock) -> None:
    error = PyWireSyntaxError("Bad", file_path="/non/existent/file.pywire", line=1)
    page = CompileErrorPage(mock_request, error)

    response = await page.render()
    content = bytes(response.body).decode()

    assert "Bad" in content
    # Should not crash even if file missing
    assert 'class="code-context"' not in content  # Use class=" to distinguish from CSS
