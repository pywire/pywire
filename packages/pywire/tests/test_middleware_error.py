import os
from typing import Any, Dict, MutableMapping

import pytest
from pywire.runtime.debug import DevErrorMiddleware
from starlette.responses import PlainTextResponse


class MockApp:
    async def __call__(self, scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
        if scope["path"] == "/error":
            raise ValueError("Test Error")
        response = PlainTextResponse("OK")
        await response(scope, receive, send)


@pytest.mark.asyncio
async def test_middleware_catches_exception() -> None:
    app = MockApp()
    middleware = DevErrorMiddleware(app)

    scope = {"type": "http", "path": "/error", "method": "GET"}

    async def receive() -> Dict[str, Any]:
        return {}

    sent_messages = []

    async def send(message: MutableMapping[str, Any]) -> None:
        sent_messages.append(message)

    await middleware(scope, receive, send)

    # Verify response start
    assert sent_messages[0]["type"] == "http.response.start"
    assert sent_messages[0]["status"] == 500

    # Verify body
    body = b"".join([m["body"] for m in sent_messages if m["type"] == "http.response.body"])
    html = body.decode("utf-8")
    assert "ValueError" in html
    assert "Test Error" in html
    assert "Traceback" in html


def test_is_framework_error_logic() -> None:
    # Unit test the path detection
    app = MockApp()
    middleware = DevErrorMiddleware(app)

    # Mocking cwd might be tricky if not standardized, but let's assume standard layout
    # pywire/src/pywire/runtime/debug.py

    # A path inside pywire/src should be framework
    fw_path = os.path.join(os.getcwd(), "pywire", "src", "pywire", "core.py")
    assert middleware._is_framework_error(fw_path) is True

    # A path in user pages should not
    user_path = os.path.join(os.getcwd(), "pages", "index.pywire")
    assert middleware._is_framework_error(user_path) is False

    # A path in virtual env site-packages (library code) -> NOT framework (it's user's deps)
    # Wait, usually we consider library code as "not user code".
    # But specifically "Framework Error" means *our* framework.
    # The logic in debug.py might define this.
    # Let's check debug.py logic if it fails.
