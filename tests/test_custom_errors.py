from pathlib import Path

from pywire.runtime.app import PyWire
from starlette.testclient import TestClient

# Custom error pages tests


def test_default_404_no_pages_dir(tmp_path: Path) -> None:
    """Verify default 404 when no pages directory exists."""
    app = PyWire(pages_dir=str(tmp_path / "nonexistent"))
    client = TestClient(app)

    response = client.get("/not-found")
    assert response.status_code == 404
    assert "Not Found" in response.text


def test_custom_error_page(tmp_path: Path) -> None:
    """Verify custom __error__ page is rendered."""
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    (pages_dir / "__error__.pywire").write_text("<h1>Error {error_code}</h1>")

    app = PyWire(pages_dir=str(pages_dir))
    client = TestClient(app)

    # Test 404
    response = client.get("/some-missing-path")
    assert response.status_code == 404
    assert "Error 404" in response.text

    # Test 500
    (pages_dir / "index.pywire").write_text("{ 1 / 0 }")

    app_prod = PyWire(pages_dir=str(pages_dir), debug=False)
    client_prod = TestClient(app_prod, raise_server_exceptions=False)

    response = client_prod.get("/")
    assert response.status_code == 500
    assert "Error 500" in response.text
