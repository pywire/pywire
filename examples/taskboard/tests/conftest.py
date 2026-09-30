"""Test setup: one app, a fresh database, and helpers for users and tabs."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import anyio
import msgpack
import pytest
from starlette.testclient import TestClient

# Settings are read at import, so configure them before importing the app.
_tmp = Path(tempfile.mkdtemp(prefix="taskboard-tests-"))
os.environ["TASKBOARD_TESTING"] = "1"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp / 'test.db'}"
os.environ["UPLOAD_DIR"] = str(_tmp / "uploads")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(scope="session")
def client():
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # "using a temporary secret"
        from main import app

    with TestClient(app) as c:
        yield c


class User:
    """A registered user: session cookie for pages, bearer token for the API."""

    def __init__(self, client: TestClient, name: str, email: str) -> None:
        from taskboard.identity import Actor, api_token, idp

        self.client = client
        self.email = email
        # Register without an earlier session cookie: pywire-auth keeps the
        # session id it finds instead of issuing a new one.
        client.cookies.clear()
        response = client.post(
            "/auth/local/register",
            data={"name": name, "email": email, "password": "correct horse"},
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text
        self.cookies = dict(response.cookies)
        client.cookies.clear()  # each request says who it is
        record = client.portal.call(idp.store.find_by_provider, "local", email)
        assert record is not None
        self.actor = Actor(id=f"local:{record['user_id']}", name=name)
        self.headers = {"Authorization": f"Bearer {api_token(self.actor)}"}

    def api(self, method: str, path: str, **kwargs: Any) -> Any:
        return self.client.request(method, path, headers=self.headers, **kwargs)

    @property
    def _cookie(self) -> dict[str, str]:
        # One client plays several people, so send this user's cookie by hand
        # and keep the shared jar empty.
        self.client.cookies.clear()
        return {"cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())}

    def get(self, path: str) -> Any:
        return self.client.get(path, headers=self._cookie, follow_redirects=False)

    def tab(self, path: str) -> Tab:
        ws = self.client.websocket_connect("/_pywire/ws", headers=self._cookie)
        return Tab(ws.__enter__(), path)


_count = 0


@pytest.fixture()
def make_user(client):
    def make(name: str) -> User:
        global _count
        _count += 1
        return User(client, name, f"{name.split()[0].lower()}{_count}@example.com")

    return make


class Tab:
    """One browser tab on a page, over pywire's WebSocket protocol."""

    def __init__(self, ws: Any, path: str) -> None:
        self.ws = ws
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
        update = self.recv(timeout)
        assert update["type"] == "update", update
        if "html" in update:
            return update["html"]
        return "".join(r.get("html", "") for r in update.get("regions", []))

    def wait_for(self, text: str, timeout: float = 3.0) -> str:
        """Updates until one contains ``text``."""
        while True:
            html = self.html(timeout)
            if text in html:
                return html

    def close(self) -> None:
        self.ws.__exit__(None, None, None)
