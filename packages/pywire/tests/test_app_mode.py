from pywire.runtime.app import PyWire
from starlette.testclient import TestClient


def test_app_mode_gating_prod() -> None:
    # Production mode: debug=False, _is_dev_mode=False
    app = PyWire(debug=False)
    app._is_dev_mode = False
    client = TestClient(app.app)

    # Dev-only routes should be 404 (not registered or gated)
    # Actually they are registered if debug=True, let's check debug=False first
    response = client.get("/_pywire/source?path=test.py")
    assert response.status_code == 404

    response = client.get("/_pywire/file/abc")
    assert response.status_code == 404

    # Script URL should be core bundle
    assert app._get_client_script_url() == "/_pywire/static/pywire.core.min.js"


def test_app_mode_gating_debug_not_dev() -> None:
    # Debug=True but NOT dev mode (e.g. 'pywire run --debug')
    app = PyWire(debug=True)
    app._is_dev_mode = False
    client = TestClient(app.app)

    # Source route SHOULD be registered but return 404 because _is_dev_mode=False
    response = client.get("/_pywire/source?path=test.py")
    assert response.status_code == 404

    # Internal flag check
    assert app._is_dev_mode is False
    assert app.debug is True

    # Still core bundle if NOT in dev mode (even if debug=True)
    assert app._get_client_script_url() == "/_pywire/static/pywire.core.min.js"


def test_app_mode_gating_dev() -> None:
    # Dev mode: debug=True, _is_dev_mode=True
    app = PyWire(debug=True)
    app._is_dev_mode = True
    client = TestClient(app.app)

    # Source route should work (if path valid, but here we just check it's not 404 initially)
    # We'll use a real file to verify it actually works
    import os

    this_file = os.path.abspath(__file__)
    response = client.get(f"/_pywire/source?path={this_file}")
    assert response.status_code == 200
    assert "test_app_mode_gating_dev" in response.text

    # Script URL should be dev bundle
    assert app._get_client_script_url() == "/_pywire/static/pywire.dev.min.js"


def test_capabilities_endpoint() -> None:
    app = PyWire()
    client = TestClient(app.app)
    response = client.get("/_pywire/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert "transports" in data
    assert "websocket" in data["transports"]
    assert "http" in data["transports"]
