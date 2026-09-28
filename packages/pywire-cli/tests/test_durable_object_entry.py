"""The generated Durable Object (cloudflare target) answers events safely."""

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import jinja2
import msgpack
import pytest

DEPLOY_TEMPLATES = (
    Path(__file__).parents[2] / "pywire-templates/src/pywire_templates/deploy"
)


@pytest.fixture()
def session_do(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The rendered pywire_do.py's DO class, run against stub Workers modules."""
    (tmp_path / "do_fixture_app.py").write_text("app = None\n")
    (tmp_path / "_routes.py").write_text("")
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in ("do_fixture_app", "_routes"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    class DurableObject:
        def __init__(self, state, env):
            pass

    workers = types.ModuleType("workers")
    workers.DurableObject = DurableObject  # type: ignore[attr-defined]
    workers.Response = MagicMock()  # type: ignore[attr-defined]
    js = types.ModuleType("js")
    js.WebSocketPair = MagicMock()  # type: ignore[attr-defined]
    pyodide = types.ModuleType("pyodide")
    ffi = types.ModuleType("pyodide.ffi")
    ffi.to_js = lambda value: value  # type: ignore[attr-defined]
    for name, module in {
        "workers": workers,
        "js": js,
        "pyodide": pyodide,
        "pyodide.ffi": ffi,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    source = (
        jinja2.Environment(loader=jinja2.FileSystemLoader(DEPLOY_TEMPLATES))
        .get_template("pywire_do.py.j2")
        .render(app_module="do_fixture_app", app_attr="app")
    )
    ns: dict = {}
    exec(compile(source, "pywire_do.py", "exec"), ns)
    yield ns["PyWireSessionDO"]
    for name in ("do_fixture_app", "_routes"):
        sys.modules.pop(name, None)


def test_failed_event_reply_hides_the_exception_text(session_do) -> None:
    do = session_do(MagicMock(), MagicMock())
    do.page = MagicMock()
    do.page.handle_event = AsyncMock(
        side_effect=RuntimeError("password authentication failed for user app")
    )
    ws = MagicMock()
    event = {"type": "event", "handler": "save", "path": "/", "data": {}, "id": 8}

    asyncio.run(do.on_webSocketMessage(ws, msgpack.packb(event)))

    reply = msgpack.unpackb(ws.send.call_args.args[0], raw=False)
    assert reply == {
        "type": "error",
        "error": "RuntimeError: An error occurred",
        "ack": 8,
    }
