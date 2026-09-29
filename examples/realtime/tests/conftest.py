"""Test helpers: drive pages over the same WebSocket protocol the browser uses."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import anyio
import msgpack
import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(scope="session")
def client():
    from main import app

    # One TestClient for the session: one event loop, like one server process.
    with TestClient(app) as c:
        yield c


class Session:
    """One browser tab connected to a page."""

    def __init__(self, ws: Any, path: str) -> None:
        self.ws = ws
        self.path = path
        assert self.recv()["type"] == "init"
        self.send({"type": "init", "path": path})
        assert self.recv()["type"] == "init_ack"

    def send(self, message: dict) -> None:
        self.ws.send_bytes(msgpack.packb(message))

    def recv(self, timeout: float = 3.0) -> dict:
        async def receive() -> Any:
            with anyio.fail_after(timeout):
                return await self.ws._send_rx.receive()

        while True:
            data = msgpack.unpackb(self.ws.portal.call(receive)["bytes"], raw=False)
            if data["type"] != "console":
                return data

    def html(self, timeout: float = 3.0) -> str:
        """HTML of the next update pushed to this tab."""
        update = self.recv(timeout)
        assert update["type"] == "update", update
        if "html" in update:
            return update["html"]
        return "".join(r.get("html", "") for r in update.get("regions", []))

    def drain(self) -> None:
        """Skip updates already on their way (e.g. from @mount)."""
        try:
            while True:
                self.recv(timeout=0.2)
        except TimeoutError:
            pass

    def event(self, handler: str, *args: Any, **data: Any) -> str:
        """Fire a handler as the browser would and return the reply's HTML.

        ``handler`` is the name in the rendered ``data-on-<event>`` attribute;
        positional ``args`` are the ones written in the template call, e.g.
        ``@click={cast(option)}``.
        """
        payload = {"args": {f"arg{i}": arg for i, arg in enumerate(args)}, **data}
        # The browser stamps each event with its page's path.
        self.send(
            {"type": "event", "handler": handler, "path": self.path, "data": payload}
        )
        return self.html()


def handler(html: str, event: str, label: str) -> tuple[str, list[Any]]:
    """Handler name and template args of the element whose text is ``label``.

    Generated names such as ``_handler_0`` aren't stable, so tests find them
    in the rendered page the way the browser does.
    """
    import html as html_lib
    import json
    import re

    for match in re.finditer(r"<(\w+)([^>]*)>([^<]*)(?=<)", html):
        attrs, text = match.group(2), match.group(3)
        if text.strip() != label:
            continue
        name = re.search(rf'data-on-{event}="([^"]+)"', attrs)
        if not name:
            continue
        args = [
            json.loads(html_lib.unescape(v))
            for _, v in sorted(re.findall(r'data-arg-(\d+)="([^"]*)"', attrs))
        ]
        return name.group(1), args
    raise AssertionError(f"no @{event} element labelled {label!r}")


def only_handler(html: str, event: str) -> str:
    """The one ``@event`` handler on the page (e.g. a single form's submit)."""
    import re

    (name,) = set(re.findall(rf'data-on-{event}="([^"]+)"', html))
    return name
