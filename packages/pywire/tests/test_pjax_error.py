from pathlib import Path

import msgpack
from pywire.runtime.app import PyWire
from pywire.runtime.page import BasePage
from starlette.testclient import TestClient


class FailingPage(BasePage):
    async def _render_template(self) -> str:
        raise RuntimeError("I failed to render!")


def test_pjax_relocate_error_trigger_reload(tmp_path: Path) -> None:
    """
    Verify that if a PJAX navigation (relocate) fails on the server side
    (e.g. 500 error during render), the server sends a 'reload' command
    to the client to force a full page refresh.
    """
    app = PyWire(debug=False, pages_dir=str(tmp_path))

    # Manually register the failing route to avoid filesystem scanning complexity
    # We need to simulate how the app registers routes
    app.router.add_route("/fail", FailingPage)

    client = TestClient(app)

    with client.websocket_connect("/_pywire/ws") as websocket:
        # Simulate PJAX navigation to the failing page
        websocket.send_bytes(msgpack.packb({"type": "relocate", "path": "/fail"}))

        # Expect response to be a 'reload' command
        data = websocket.receive_bytes()
        message = msgpack.unpackb(data)

        assert message["type"] == "reload", f"Expected 'reload', got {message['type']}"
