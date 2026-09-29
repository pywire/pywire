"""SPA navigation runs the target page's @before_load and @init hooks.

A relocate renders the page through an internal request and keeps a second
instance for the connection's events. Both must have run the page's hooks,
or the HTML and every later update render the page without its data.
"""

from pathlib import Path
from typing import Any

import msgpack
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire

ITEM = """---
name = wire("")
clicks = wire(0)

@before_load
def check():
    assert params.item_id != "forbidden"

@init
async def load():
    name.value = f"item {params.item_id}"

def click():
    clicks.value += 1
---
<h1 id="name">name={name}</h1>
<p id="clicks">clicks={clicks}</p>
<button @click={click}>click</button>
"""


def _recv(ws: Any) -> dict:
    while True:
        data = msgpack.unpackb(ws.receive_bytes(), raw=False)
        if data["type"] != "console":
            return data


def _html(update: dict) -> str:
    assert update["type"] == "update", update
    if "html" in update:
        return update["html"]
    return "".join(r.get("html", "") for r in update.get("regions", []))


def test_relocate_runs_init_for_the_html_and_for_later_events(tmp_path: Path):
    pages = tmp_path / "pages"
    (pages / "items").mkdir(parents=True)
    (pages / "index.wire").write_text("<a href='/items/7'>item</a>\n")
    (pages / "items" / "[item_id].wire").write_text(ITEM)
    app = PyWire(pages_dir=str(pages))

    with TestClient(app) as client:
        with client.websocket_connect("/_pywire/ws") as ws:
            assert _recv(ws)["type"] == "init"
            ws.send_bytes(msgpack.packb({"type": "init", "path": "/"}))
            assert _recv(ws)["type"] == "init_ack"

            ws.send_bytes(msgpack.packb({"type": "relocate", "path": "/items/7"}))
            assert "name=item 7" in _html(_recv(ws))

            ws.send_bytes(
                msgpack.packb(
                    {
                        "type": "event",
                        "handler": "click",
                        "path": "/items/7",
                        "data": {},
                        "id": 1,
                    }
                )
            )
            update = _html(_recv(ws))
            assert "clicks=1" in update
            # The instance handling events ran @init too.
            assert "name=" not in update or "name=item 7" in update
            ws.send_bytes(msgpack.packb({"type": "relocate", "path": "/"}))
            _recv(ws)
            ws.send_bytes(msgpack.packb({"type": "relocate", "path": "/items/8"}))
            assert "name=item 8" in _html(_recv(ws))
