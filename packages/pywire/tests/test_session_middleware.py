"""SessionMiddleware cookie issuance: Secure flag and id rotation."""

from __future__ import annotations

from typing import Optional

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from pywire.runtime.session_middleware import SessionMiddleware, rotate_session
from pywire.runtime.session_store import MemorySessionStore

SECRET = "k" * 32


def _client(
    *, base_url: str = "http://testserver", cookie_secure: Optional[bool] = None
) -> tuple[TestClient, MemorySessionStore]:
    store = MemorySessionStore()

    async def show(request: Request) -> PlainTextResponse:
        return PlainTextResponse(request.scope["pywire_session_id"])

    async def remember(request: Request) -> PlainTextResponse:
        sid = request.scope["pywire_session_id"]
        await store.set(sid, {"n": 1}, ttl=60)
        return PlainTextResponse(sid)

    async def login(request: Request) -> PlainTextResponse:
        new = await rotate_session(request.scope, store, 60)
        return PlainTextResponse(new)

    app = Starlette(
        routes=[
            Route("/show", show),
            Route("/remember", remember),
            Route("/login", login, methods=["POST"]),
        ]
    )
    app.add_middleware(
        SessionMiddleware,
        session_store=store,
        secret_key=SECRET,
        cookie_secure=cookie_secure,
    )
    return TestClient(app, base_url=base_url), store


def test_cookie_is_secure_over_https_only() -> None:
    plain, _ = _client()
    assert "Secure" not in plain.get("/show").headers["set-cookie"]
    tls, _ = _client(base_url="https://testserver")
    assert "Secure" in tls.get("/show").headers["set-cookie"]


def test_cookie_secure_can_be_forced() -> None:
    client, _ = _client(cookie_secure=True)
    assert "Secure" in client.get("/show").headers["set-cookie"]


def test_existing_session_gets_no_new_cookie() -> None:
    client, _ = _client()
    first = client.get("/remember").text
    resp = client.get("/show")
    assert resp.text == first
    assert "set-cookie" not in resp.headers


def test_rotate_session_moves_data_and_reissues_cookie() -> None:
    client, store = _client()
    old = client.get("/remember").text
    resp = client.post("/login")
    new = resp.text
    assert new != old
    assert f"pywire_session={new}." in resp.headers["set-cookie"]
    assert store._data.get(old) is None
    assert client.get("/show").text == new
