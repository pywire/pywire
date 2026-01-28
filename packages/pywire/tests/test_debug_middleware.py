from pathlib import Path
from typing import Any, MutableMapping

import pytest
from pywire.compiler.exceptions import PyWireSyntaxError
from pywire.runtime.debug import DevErrorMiddleware
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient


def test_debug_middleware_catches_generic_exception() -> None:
    async def app(scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
        raise ValueError("Oops!")

    debug_app = DevErrorMiddleware(app)
    client = TestClient(debug_app)

    response = client.get("/")
    assert response.status_code == 500
    assert "ValueError" in response.text
    assert "Oops!" in response.text
    assert "Traceback" in response.text


def test_debug_middleware_catches_syntax_error(tmp_path: Path) -> None:
    # Create a dummy file for the syntax error to point to
    file_path = tmp_path / "broken.pywire"
    file_path.write_text("line 1\nline 2\nline 3")

    async def app(scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
        raise PyWireSyntaxError("Bad tags", file_path=str(file_path), line=2)

    debug_app = DevErrorMiddleware(app)
    client = TestClient(debug_app)

    response = client.get("/")
    assert response.status_code == 500
    assert "PyWire Syntax Error" in response.text
    assert "Bad tags" in response.text
    assert "line 2" in response.text
    # Check context
    assert "line 1" in response.text
    assert "line 3" in response.text


def test_debug_middleware_skips_non_http() -> None:
    # Only HTTP scope should be caught by the middleware logic
    async def app(scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.accept"})
            raise RuntimeError("WS Crash")
        response = PlainTextResponse("OK")
        await response(scope, receive, send)

    debug_app = DevErrorMiddleware(app)
    client = TestClient(debug_app)

    # Should throw in TestClient because it's not swallowed by response rendering for non-http
    with pytest.raises(RuntimeError, match="WS Crash"):
        with client.websocket_connect("/"):
            pass


def test_debug_middleware_attribute_forwarding() -> None:
    class MockApp:
        def __init__(self) -> None:
            self.foo = "bar"

        async def __call__(self, scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
            pass

    mock_app = MockApp()
    debug_app = DevErrorMiddleware(mock_app)
    assert debug_app.foo == "bar"
