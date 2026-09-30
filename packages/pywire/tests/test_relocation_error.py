import base64
from pathlib import Path
from typing import Any, cast

import msgpack
import pytest
from pywire.runtime.app import PyWire
from starlette.testclient import TestClient


@pytest.fixture
def app_dev(tmp_path: Path) -> PyWire:
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    (pages_dir / "index.wire").write_text(
        """!path { 'a': '/a', 'b': '/b' }
---
# Python
---
<h1>Index</h1>"""
    )

    app = PyWire(pages_dir=str(pages_dir), debug=True)
    app._is_dev_mode = True
    return app


def test_source_relocation_endpoint(app_dev: PyWire, tmp_path: Path) -> None:
    client = TestClient(app_dev.app, base_url="http://localhost")

    # Test /_pywire/source
    test_file = tmp_path / "pages" / "test.py"
    test_file.write_text("print('hello')")

    response = client.get(f"/_pywire/source?path={test_file}")
    assert response.status_code == 200
    assert response.text == "print('hello')"
    assert response.headers["content-type"] == "text/plain; charset=utf-8"

    # Test /_pywire/file (base64 encoded)
    # Using URL-safe base64 logic from app.py
    filename = str(test_file)
    encoded = base64.b64encode(filename.encode()).decode()
    encoded = encoded.replace("+", "-").replace("/", "_").rstrip("=")

    response = client.get(f"/_pywire/file/{encoded}")
    assert response.status_code == 200
    assert response.text == "print('hello')"


def test_source_relocation_security(app_dev: PyWire) -> None:
    client = TestClient(app_dev.app, base_url="http://localhost")

    # Should 404 if debug is off
    app_dev.debug = False
    response = client.get("/_pywire/source?path=/etc/passwd")
    assert response.status_code == 404

    # Should 404 if not in dev mode
    app_dev.debug = True
    app_dev._is_dev_mode = False
    response = client.get("/_pywire/source?path=/etc/passwd")
    assert response.status_code == 404


def test_spa_relocation_failure_forces_reload(app_dev: PyWire) -> None:
    client = TestClient(app_dev.app)

    with client.websocket_connect("/_pywire/ws") as websocket:
        # Drain init message
        websocket.receive_bytes()

        # Trigger a relocation to a non-existent path that will cause an error
        # normally _handle_relocate catches route not found and serves 404 page,
        # but if we FORCE an exception in the router or page creation, it should trigger 'reload'.

        # We can mock the router to throw
        original_match = app_dev.router.match

        def mock_match(path: str) -> Any:
            if path == "/fail-hard":
                raise RuntimeError("Hard failure")
            return original_match(path)

        cast(Any, app_dev.router).match = mock_match

        websocket.send_bytes(msgpack.packb({"type": "relocate", "path": "/fail-hard"}))

        data_bytes = websocket.receive_bytes()
        data = msgpack.unpackb(data_bytes, raw=False)

        assert data["type"] == "reload"


def test_relocate_never_sends_a_non_html_body(app_dev: PyWire, tmp_path: Path) -> None:
    """A relocate to a debug endpoint must not return file contents over the socket.

    The body of a non-HTML response (here /_pywire/source) is not a page:
    the client is told to reload so the browser fetches it itself.
    """
    test_file = tmp_path / "pages" / "secret.py"
    test_file.write_text("TOKEN = 'do-not-leak'")
    client = TestClient(app_dev.app, base_url="http://localhost")

    with client.websocket_connect("/_pywire/ws") as websocket:
        websocket.receive_bytes()
        websocket.send_bytes(
            msgpack.packb(
                {"type": "relocate", "path": f"/_pywire/source?path={test_file}"}
            )
        )
        raw = websocket.receive_bytes()
        assert b"do-not-leak" not in raw
        assert msgpack.unpackb(raw, raw=False) == {"type": "reload"}


def test_relocate_to_page_still_sends_html(app_dev: PyWire) -> None:
    client = TestClient(app_dev.app, base_url="http://localhost")
    with client.websocket_connect("/_pywire/ws") as websocket:
        websocket.receive_bytes()
        websocket.send_bytes(msgpack.packb({"type": "relocate", "path": "/a"}))
        data = msgpack.unpackb(websocket.receive_bytes(), raw=False)
        assert data["type"] == "update"
        assert "<h1>Index</h1>" in data["html"]
