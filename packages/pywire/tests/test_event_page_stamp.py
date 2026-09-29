"""An event sent from one page never reaches the next page after SPA nav."""

import shutil
import tempfile
from pathlib import Path

import msgpack
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire
from pywire.runtime.protocol import for_another_page

A = """---
hits = wire(0)

def act():
    hits.value += 1
---
<button @click={act}>A {hits}</button>
"""

B = """---
wiped = wire(False)

def act():
    wiped.value = True
---
<button @click={act}>B wiped={wiped}</button>
"""


def _recv(ws):
    return msgpack.unpackb(ws.receive_bytes(), raw=False)


def test_an_event_from_the_previous_page_is_dropped():
    root = Path(tempfile.mkdtemp())
    pages = root / "pages"
    pages.mkdir()
    (pages / "a.wire").write_text(A)
    (pages / "b.wire").write_text(B)
    try:
        client = TestClient(PyWire(pages_dir=str(pages)))
        with client.websocket_connect("/_pywire/ws") as ws:
            assert _recv(ws)["type"] == "init"
            ws.send_bytes(msgpack.packb({"type": "init", "path": "/a"}))
            assert _recv(ws)["type"] == "init_ack"

            ws.send_bytes(msgpack.packb({"type": "relocate", "path": "/b"}))
            moved = _recv(ws)
            assert moved["type"] == "update" and "wiped=False" in moved["html"]

            # Typed on /a, debounced, sent after the move: same handler name.
            ws.send_bytes(
                msgpack.packb(
                    {
                        "type": "event",
                        "handler": "act",
                        "path": "/a",
                        "data": {},
                        "id": 7,
                    }
                )
            )
            reply = _recv(ws)
            assert reply == {"type": "update", "regions": [], "ack": 7}

            ws.send_bytes(
                msgpack.packb(
                    {
                        "type": "event",
                        "handler": "act",
                        "path": "/b",
                        "data": {},
                        "id": 8,
                    }
                )
            )
            reply = _recv(ws)
            assert reply["ack"] == 8 and "wiped=True" in str(reply)
    finally:
        shutil.rmtree(root, ignore_errors=True)


class _Page:
    def __init__(self, path, root_path=""):
        self.request = type("R", (), {"scope": {"path": path, "root_path": root_path}})


def test_page_stamps_compare_paths_only():
    assert not for_another_page(_Page("/a"), "/a?x=1")
    assert not for_another_page(_Page("/café"), "/caf%C3%A9")
    assert not for_another_page(_Page("/a", "/app"), "/app/a")
    assert for_another_page(_Page("/b"), "/a")
    # Old clients send no stamp; pages without a request can't be checked.
    assert not for_another_page(_Page("/b"), None)
    assert not for_another_page(object(), "/a")
