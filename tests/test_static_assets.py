from pathlib import Path

import pytest
from pywire.runtime.app import PyWire
from starlette.testclient import TestClient


def test_static_asset_serving(tmp_path: Path) -> None:
    """Verify static asset serving."""
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    (pages_dir / "index.pywire").write_text("<div>Home</div>", encoding="utf-8")

    static_dir = tmp_path / "static_assets"
    static_dir.mkdir()
    (static_dir / "style.css").write_text("body { background: blue; }", encoding="utf-8")

    app = PyWire(pages_dir=str(pages_dir), static_dir=str(static_dir))
    client = TestClient(app)

    response = client.get("/static/style.css")
    assert response.status_code == 200
    assert response.text == "body { background: blue; }"

    # Verify default is disabled
    app_default = PyWire(pages_dir=str(pages_dir))
    client_default = TestClient(app_default)
    response_default = client_default.get("/static/style.css")
    assert response_default.status_code == 404


def test_smart_static_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify smart resolution of static_dir (root vs src fallback)."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    # Setup 1: Exists in root
    static_root = tmp_path / "static_root"
    static_root.mkdir()

    app1 = PyWire(static_dir="static_root")
    assert app1.static_dir == static_root.resolve()

    # Setup 2: Exists in src/ (fallback)
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    static_src = src_dir / "static_src"
    static_src.mkdir()

    app2 = PyWire(static_dir="static_src")
    assert app2.static_dir == static_src.resolve()


def test_static_dir_missing_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify warning when static directory is missing."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    PyWire(static_dir="non_existent")
    captured = capsys.readouterr()
    assert "Warning: Configured static directory" in captured.out
    assert "non_existent" in captured.out


def test_custom_static_path(tmp_path: Path) -> None:
    """Verify static assets can be served from a custom URL path."""
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    static_dir = tmp_path / "assets"
    static_dir.mkdir()
    (static_dir / "test.js").write_text("console.log('test')", encoding="utf-8")

    app = PyWire(pages_dir=str(pages_dir), static_dir=str(static_dir), static_path="/public")
    client = TestClient(app)

    response = client.get("/public/test.js")
    assert response.status_code == 200
    assert response.text == "console.log('test')"
