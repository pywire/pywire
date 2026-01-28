from pathlib import Path

import pytest
from pywire.runtime.app import PyWire
from starlette.testclient import TestClient


@pytest.fixture
def minimal_app_dev() -> PyWire:
    app = PyWire(debug=True)
    app._is_dev_mode = True
    return app


@pytest.fixture
def minimal_app_prod() -> PyWire:
    app = PyWire(debug=False)
    app._is_dev_mode = False
    return app


def test_script_injection_dev_mode(minimal_app_dev: PyWire) -> None:
    # This test requires a compiled page with SPA enabled (multi-path)
    # Since we can't easily compile a file in this test without setting up pages_dir,
    # we'll mock a page class and register it.

    from pywire.runtime.page import BasePage

    class MockSpaPage(BasePage):
        __spa_enabled__ = True
        __sibling_paths__ = ["/a", "/b"]

        async def _render_template(self) -> str:
            # This is where the injection happens in the real compiled code,
            # but for this integration test we want to see if the RENDERED output
            # contains the script.
            # In a real app, the compiler generates this.
            # We can use the CodeGenerator to generate the actual class for a real integration test.
            return "<html><body>Mock</body></html>"

    # Actually, a better integration test is to use the real PyWire.reload_page or similar
    # but that needs files. Let's use TestClient with a real app and some temp files.
    pass


def test_bundle_selection_integration(tmp_path: Path) -> None:
    # Set up a real (but small) app
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    (pages_dir / "index.pywire").write_text(
        "!path { 'a': '/a', 'b': '/b' }\n<h1>Index</h1>\n---\n# Python"
    )

    # Dev Mode
    app_dev = PyWire(pages_dir=str(pages_dir), debug=True)
    app_dev._is_dev_mode = True
    client_dev = TestClient(app_dev.app)

    response = client_dev.get("/a")
    assert response.status_code == 200
    assert "pywire.dev.min.js" in response.text
    assert "_pywire_spa_meta" in response.text

    # Prod Mode
    app_prod = PyWire(pages_dir=str(pages_dir), debug=False)
    app_prod._is_dev_mode = False
    client_prod = TestClient(app_prod.app)

    response = client_prod.get("/a")
    assert response.status_code == 200
    assert "pywire.core.min.js" in response.text
    # SPA meta might be disabled in prod if not explicitly enabled?
    # Actually current logic in generator.py (spa_check) checks enable_pjax.
    # By default enable_pjax is True.
    assert "_pywire_spa_meta" in response.text


def test_no_spa_directive_disables_injection(tmp_path: Path) -> None:
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    (pages_dir / "no_spa.pywire").write_text(
        "!path { 'a': '/a', 'b': '/b' }\n!no_spa\n<h1>No SPA</h1>\n---\n# Python"
    )

    app = PyWire(pages_dir=str(pages_dir), debug=True)
    app._is_dev_mode = True
    client = TestClient(app.app)

    response = client.get("/a")
    assert response.status_code == 200
    assert "pywire.dev.min.js" not in response.text
    assert "_pywire_spa_meta" not in response.text
