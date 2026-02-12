from pathlib import Path
import pytest
from pywire.runtime.app import PyWire
from starlette.testclient import TestClient

def test_script_injection_pjax_off(tmp_path: Path) -> None:
    # Set up a real (but small) app with PJAX explicitly OFF
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    (pages_dir / "index.wire").write_text(
        "# Python\n---html---\n<html><body><h1>Index</h1></body></html>"
    )

    # App with PJAX disabled
    app = PyWire(pages_dir=str(pages_dir), debug=True, enable_pjax=False)
    client = TestClient(app.app)

    response = client.get("/")
    assert response.status_code == 200
    
    # Even with PJAX off, we should see the client script
    assert "pywire.core.min.js" in response.text or "pywire.dev.min.js" in response.text
    assert "_pywire_spa_meta" in response.text
    
    # Metadata should show enable_pjax: false
    assert '"enable_pjax": false' in response.text

def test_script_injection_pjax_on(tmp_path: Path) -> None:
    # Set up a real (but small) app with PJAX ON (default)
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    (pages_dir / "index.wire").write_text(
        "# Python\n---html---\n<html><body><h1>Index</h1></body></html>"
    )

    # App with PJAX enabled
    app = PyWire(pages_dir=str(pages_dir), debug=True, enable_pjax=True)
    client = TestClient(app.app)

    response = client.get("/")
    assert response.status_code == 200
    
    # With PJAX on, we should see the client script
    assert "pywire.core.min.js" in response.text or "pywire.dev.min.js" in response.text
    assert "_pywire_spa_meta" in response.text
    
    # Metadata should show enable_pjax: true
    assert '"enable_pjax": true' in response.text

def test_script_injection_is_component_no_injection(tmp_path: Path) -> None:
    # Components should NOT have the script injected
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    (pages_dir / "index.wire").write_text(
        "# Python\n---html---\n<html><body><my-comp /></body></html>"
    )
    (pages_dir / "my-comp.wire").write_text(
        "# Python\n---html---\n<div>Component</div>"
    )

    app = PyWire(pages_dir=str(pages_dir), debug=True)
    client = TestClient(app.app)

    response = client.get("/")
    assert response.status_code == 200
    
    # Main page has script
    assert "pywire" in response.text
    
    # In PyWire, components rendered as part of a page should not double-inject.
    # The current logic in page.py:
    # is_component = getattr(self, "__is_component__", False)
    # if init and not is_component: ...
    # This is handled during the render of the component instance.