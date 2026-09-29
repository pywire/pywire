"""The generated Cloudflare target runs the whole app in one Durable Object.

The rendered entry.py and pywire_do.py run here against stub Workers modules
and a real PyWire app, so what they do with requests and sockets is the app's
own behaviour, as under `pywire run --workers 1`.
"""

import asyncio
import sys
import types
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import jinja2
import msgpack
import pytest

DEPLOY_TEMPLATES = (
    Path(__file__).parents[2] / "pywire-templates/src/pywire_templates/deploy"
)

SHARED = "from pywire import wire\n\ntotal = wire(0)\n"

INDEX = """---
import shared

mine = wire(0)

def bump():
    mine.value += 1
    shared.total.value += 1
---
<p>total={shared.total} mine={mine}</p>
<button @click={bump}>bump</button>
"""


def _render(name: str, **context: Any) -> str:
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(DEPLOY_TEMPLATES))
    return env.get_template(name).render(**context)


class FakeHeaders(dict):
    """Headers look names up case-insensitively, like the Fetch API's."""

    def get(self, name: str, default: Any = None) -> Any:
        return super().get(name.lower(), default)

    def has(self, name: str) -> bool:
        return name.lower() in self


class FakeRequest:
    def __init__(self, url: str, headers: dict[str, str] | None = None) -> None:
        self.url = url
        self.method = "GET"
        self.headers = FakeHeaders({k.lower(): v for k, v in (headers or {}).items()})
        self.js_object = self


class FakeBuffer:
    """A JS ArrayBuffer as a message event carries it."""

    def __init__(self, data: bytes) -> None:
        self.data = data


class FakeSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.binaryType = "blob"
        self.listeners: dict[str, Any] = {}
        self.sent: list[Any] = []
        self.closed: tuple[int, str] | None = None

    def accept(self) -> None:
        self.accepted = True

    def addEventListener(self, name: str, listener: Any) -> None:
        self.listeners[name] = listener

    def removeEventListener(self, name: str, listener: Any) -> None:
        if self.listeners.get(name) is listener:
            del self.listeners[name]

    def send(self, data: Any) -> None:
        self.sent.append(data)

    def close(self, code: int, reason: str) -> None:
        self.closed = (code, reason)

    # What the browser does.
    def client_send(self, message: dict) -> None:
        event = types.SimpleNamespace(data=FakeBuffer(msgpack.packb(message)))
        self.listeners["message"](event)

    def client_close(self) -> None:
        self.listeners["close"](types.SimpleNamespace(code=1001))

    def messages(self) -> list[dict]:
        return [msgpack.unpackb(bytes(m), raw=False) for m in self.sent]


class FakeProxy:
    def __init__(self, fn: Any) -> None:
        self.fn = fn
        self.destroyed = False

    def __call__(self, *args: Any) -> Any:
        assert not self.destroyed, "called a destroyed proxy"
        return self.fn(*args)

    def destroy(self) -> None:
        self.destroyed = True


class FakeNamespace:
    """env.PYWIRE_APP: a Durable Object namespace with one object per name."""

    def __init__(self, do_class: Any, env: Any) -> None:
        self.do_class = do_class
        self.env = env
        self.objects: dict[str, Any] = {}

    def getByName(self, name: str) -> Any:
        if name not in self.objects:
            self.objects[name] = self.do_class(None, self.env)
        return self.objects[name]


@pytest.fixture()
def cloudflare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Deploy files for a src/ layout app with a module-level wire."""
    pages = tmp_path / "src" / "pages"
    pages.mkdir(parents=True)
    (tmp_path / "src" / "__init__.py").write_text("")
    (tmp_path / "src" / "main.py").write_text(
        "from pathlib import Path\n"
        "from pywire import PyWire\n"
        "app = PyWire(pages_dir=Path(__file__).parent / 'pages')\n"
    )
    (tmp_path / "src" / "shared.py").write_text(SHARED)
    (pages / "index.wire").write_text(INDEX)
    # The build's _routes.py registers the prebuilt pages; compiling them
    # here does the same.
    (tmp_path / "_routes.py").write_text(
        "from src.main import app\napp._load_pages()\n"
    )
    (tmp_path / "pywire_do.py").write_text(
        _render("pywire_do.py.j2", app_module="src.main", app_attr="app")
    )
    (tmp_path / "entry.py").write_text(_render("entry.py.j2"))
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delenv("PYWIRE_PREBUILT", raising=False)
    monkeypatch.delenv("APP_GREETING", raising=False)

    sockets: list[FakeSocket] = []
    http_calls: list[str] = []

    class DurableObject:
        def __init__(self, ctx: Any, env: Any) -> None:
            self.ctx = ctx
            self.env = env

    class WorkerEntrypoint(DurableObject):
        pass

    class WebSocketPair:
        @staticmethod
        def new() -> Any:
            server = FakeSocket()
            sockets.append(server)
            return types.SimpleNamespace(object_values=lambda: (FakeSocket(), server))

    class Uint8Array:
        def __init__(self, buffer: FakeBuffer) -> None:
            self.buffer = buffer

        @staticmethod
        def new(buffer: FakeBuffer) -> "Uint8Array":
            return Uint8Array(buffer)

        def to_bytes(self) -> bytes:
            return self.buffer.data

    class Response:
        @staticmethod
        def new(body: Any, status: int, webSocket: Any = None) -> Any:
            return types.SimpleNamespace(body=body, status=status, webSocket=webSocket)

    async def asgi_fetch(app: Any, request: FakeRequest, env: Any) -> Any:
        """asgi.fetch: lifespan startup, the request, lifespan shutdown."""
        startup = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

        async def lifespan_receive() -> dict:
            return next(startup)

        async def ignore(message: dict) -> None:
            pass

        await app({"type": "lifespan"}, lifespan_receive, ignore)
        http_calls.append(request.url)
        body: list[bytes] = []
        status: list[int] = []

        async def receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict) -> None:
            if message["type"] == "http.response.start":
                status.append(message["status"])
            elif message["type"] == "http.response.body":
                body.append(message.get("body", b""))

        path = urlsplit(request.url).path
        scope = {
            "type": "http",
            "method": request.method,
            "path": path,
            "query_string": b"",
            "headers": [(k.encode(), v.encode()) for k, v in request.headers.items()],
            "scheme": "https",
            "http_version": "1.1",
            "root_path": "",
            "server": ("example.com", 443),
        }
        await app(scope, receive, send)
        return types.SimpleNamespace(status=status[0], text=b"".join(body).decode())

    workers = types.ModuleType("workers")
    workers.DurableObject = DurableObject  # type: ignore[attr-defined]
    workers.WorkerEntrypoint = WorkerEntrypoint  # type: ignore[attr-defined]
    js = types.ModuleType("js")
    js.Headers = types.SimpleNamespace(new=FakeHeaders)  # type: ignore[attr-defined]
    js.Object = types.SimpleNamespace(keys=lambda env: list(vars(env)))  # type: ignore[attr-defined]
    js.Request = types.SimpleNamespace(new=lambda req, headers: req)  # type: ignore[attr-defined]
    js.Response = Response  # type: ignore[attr-defined]
    js.Uint8Array = Uint8Array  # type: ignore[attr-defined]
    js.WebSocketPair = WebSocketPair  # type: ignore[attr-defined]
    pyodide = types.ModuleType("pyodide")
    ffi = types.ModuleType("pyodide.ffi")
    ffi.create_proxy = FakeProxy  # type: ignore[attr-defined]
    ffi.to_js = lambda value: value  # type: ignore[attr-defined]
    asgi = types.ModuleType("asgi")
    asgi.fetch = asgi_fetch  # type: ignore[attr-defined]
    for name, module in {
        "workers": workers,
        "js": js,
        "pyodide": pyodide,
        "pyodide.ffi": ffi,
        "asgi": asgi,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    loaded = ("entry", "pywire_do", "_routes", "src", "src.main", "shared")
    for name in loaded:
        monkeypatch.delitem(sys.modules, name, raising=False)
    import entry
    import pywire_do

    env = types.SimpleNamespace(
        PYWIRE_SECRET_KEY="k" * 32,
        APP_GREETING="hello",
        ASSETS=object(),
    )
    env.PYWIRE_APP = FakeNamespace(pywire_do.PyWireAppDO, env)
    yield types.SimpleNamespace(
        entry=entry.Default(None, env),
        env=env,
        sockets=sockets,
        http_calls=http_calls,
    )
    for name in loaded:
        sys.modules.pop(name, None)


async def _settle() -> None:
    for _ in range(50):
        await asyncio.sleep(0)
    await asyncio.sleep(0.05)


async def _open_tab(cf: Any) -> FakeSocket:
    response = await cf.entry.fetch(
        FakeRequest("https://example.com/_pywire/ws", {"Upgrade": "websocket"})
    )
    assert response.status == 101
    socket = cf.sockets[-1]
    await _settle()
    socket.client_send({"type": "init", "path": "/"})
    await _settle()
    return socket


async def _click(socket: FakeSocket, event_id: int) -> str:
    socket.client_send(
        {"type": "event", "handler": "bump", "path": "/", "data": {}, "id": event_id}
    )
    await _settle()
    reply = next(m for m in reversed(socket.messages()) if m.get("ack") == event_id)
    return str(reply)


def test_every_request_goes_to_one_app_object(cloudflare) -> None:
    async def run() -> None:
        await cloudflare.entry.fetch(FakeRequest("https://example.com/"))
        await _open_tab(cloudflare)
        await _open_tab(cloudflare)

    asyncio.run(run())
    assert list(cloudflare.env.PYWIRE_APP.objects) == ["app"]


def test_tabs_share_module_wires_and_keep_their_own_page(cloudflare) -> None:
    async def run() -> tuple[str, str]:
        tab_a = await _open_tab(cloudflare)
        tab_b = await _open_tab(cloudflare)
        await _click(tab_a, 1)
        await _click(tab_a, 2)
        return await _click(tab_b, 1), str(tab_a.messages())

    after_b, _ = asyncio.run(run())
    # Tab B sees tab A's two clicks, and its own page counts only its own.
    assert "total=3" in after_b
    assert "mine=1" in after_b


def test_sockets_speak_binary_to_the_apps_websocket_route(cloudflare) -> None:
    async def run() -> FakeSocket:
        return await _open_tab(cloudflare)

    socket = asyncio.run(run())
    assert socket.accepted
    assert socket.binaryType == "arraybuffer"
    kinds = [m["type"] for m in socket.messages()]
    assert kinds[:2] == ["init", "init_ack"]


def test_closed_tab_releases_its_socket(cloudflare) -> None:
    async def run() -> FakeSocket:
        socket = await _open_tab(cloudflare)
        socket.client_close()
        await _settle()
        return socket

    socket = asyncio.run(run())
    assert socket.closed == (1000, "")
    assert socket.listeners == {}
    app = sys.modules["src.main"].app
    assert not app.ws_handler.active_connections


def test_pages_render_in_the_object_with_worker_vars_in_environ(cloudflare) -> None:
    import os

    async def run() -> Any:
        return await cloudflare.entry.fetch(FakeRequest("https://example.com/"))

    response = asyncio.run(run())
    assert response.status == 200
    assert "total=0" in response.text
    assert os.environ["APP_GREETING"] == "hello"
    assert "ASSETS" not in os.environ


def test_http_requests_do_not_shut_the_app_down(cloudflare) -> None:
    """asgi.fetch's per-request lifespan must not reach the app's lifespan."""
    closed: list[bool] = []

    async def run() -> None:
        await cloudflare.entry.fetch(FakeRequest("https://example.com/"))
        app = sys.modules["src.main"].app
        store = app.session_store
        original = store.close

        async def close() -> None:
            closed.append(True)
            await original()

        store.close = close
        await cloudflare.entry.fetch(FakeRequest("https://example.com/"))

    asyncio.run(run())
    assert closed == []
    assert len(cloudflare.http_calls) == 2


def test_concurrent_first_requests_load_the_app_once(cloudflare) -> None:
    pywire_do = sys.modules["pywire_do"]
    imports: list[Any] = []
    import_app = pywire_do._import_app

    async def counting_import(env: Any) -> Any:
        imports.append(env)
        return await import_app(env)

    pywire_do._import_app = counting_import

    async def run() -> None:
        await asyncio.gather(
            *(
                cloudflare.entry.fetch(FakeRequest("https://example.com/"))
                for _ in range(3)
            )
        )

    asyncio.run(run())
    assert len(imports) == 1
    assert len(cloudflare.http_calls) == 3
