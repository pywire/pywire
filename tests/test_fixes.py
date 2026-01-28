from pathlib import Path

from pywire.runtime.app import PyWire
from starlette.testclient import TestClient


def test_synchronous_loop(tmp_path: Path) -> None:
    """Verify that synchronous lists work in $for loops."""

    page_content = """
<ul>
    <li $for={item in items}>{item}</li>
</ul>
---
items = [1, 2, 3]
---
"""

    (tmp_path / "index.pywire").write_text(page_content, encoding="utf-8")

    app = PyWire(str(tmp_path))
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200
    assert "<li>1</li>" in response.text
    assert "<li>2</li>" in response.text
    assert "<li>3</li>" in response.text


def test_static_path_config(tmp_path: Path) -> None:
    """Verify static asset serving with custom URL path."""

    # Create pages dir
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    (pages_dir / "index.pywire").write_text("<div>Home</div>", encoding="utf-8")

    # Create static dir
    static_dir = tmp_path / "assets"
    static_dir.mkdir()
    (static_dir / "logo.png").write_text("fake image", encoding="utf-8")

    # Configure custom path
    app = PyWire(pages_dir=str(pages_dir), static_dir=str(static_dir), static_path="/public")
    client = TestClient(app)

    # Request at new path
    response = client.get("/public/logo.png")
    assert response.status_code == 200
    assert response.text == "fake image"

    # Verify old path 404
    response = client.get("/static/logo.png")
    assert response.status_code == 404

    # Verify default relative usage
    # If user didn't specify static_path, it defaults to /static
    app_default = PyWire(pages_dir=str(pages_dir), static_dir=str(static_dir))
    client_default = TestClient(app_default)
    response = client_default.get("/static/logo.png")
    assert response.status_code == 200
