import asyncio
import unittest
from typing import Any, Dict, Optional, cast
from unittest.mock import MagicMock

import msgpack  # type: ignore[import-untyped]
from pywire.runtime.http_transport import HTTPSession, HTTPTransportHandler
from pywire.runtime.page import BasePage
from starlette.requests import Request


class MockRequest:
    @staticmethod
    def create(
        body_data: Optional[Dict[str, Any]] = None,
        query_params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        path: str = "/",
    ) -> Request:
        body = msgpack.packb(body_data) if body_data is not None else b""
        scope = {
            "type": "http",
            "path": path,
            "query_string": b"",
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            "client": ["127.0.0.1", 1234],
            "method": "POST",
        }
        if query_params:
            from urllib.parse import urlencode

            scope["query_string"] = urlencode(query_params).encode()

        async def receive() -> Dict[str, Any]:
            return {"type": "http.request", "body": body, "more_body": False}

        return Request(scope, receive=receive)


class MockPage(BasePage):
    async def _render_template(self) -> str:
        return "<div>HTTP Page</div>"

    async def handle_event(self, name: str, data: dict) -> Any:  # Response
        return await self.render()


class TestHTTPTransportHandler(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        import msgpack
        import pywire.runtime.http_transport as ht

        print(f"\nDEBUG: ht module: {ht.__file__}")
        print(f"DEBUG: msgpack module: {msgpack.__file__}")
        self.app = MagicMock()
        self.app.router = MagicMock()
        self.handler = HTTPTransportHandler(self.app)

    async def test_create_session(self) -> None:
        self.app.router.match.return_value = (MockPage, {}, "main")
        request = MockRequest.create(body_data={"path": "/test"})

        response = await self.handler.create_session(request)
        data = msgpack.unpackb(response.body, raw=False)

        self.assertIn("sessionId", data)
        session_id = data["sessionId"]
        self.assertIn(session_id, self.handler.sessions)
        self.assertEqual(self.handler.sessions[session_id].path, "/test")
        self.assertIsInstance(self.handler.sessions[session_id].page, MockPage)

    async def test_poll_timeout(self) -> None:
        session_id = "test-session"
        session = HTTPSession(session_id=session_id, path="/")
        self.handler.sessions[session_id] = session

        request = MockRequest.create(query_params={"session": session_id})

        # Patch timeout to be very short for test
        def timeout_side_effect(coro: asyncio.Task, timeout: float) -> None:
            cast(Any, coro).close()
            raise asyncio.TimeoutError

        with unittest.mock.patch("asyncio.wait_for", side_effect=timeout_side_effect):
            response = await self.handler.poll(request)
            data = msgpack.unpackb(response.body, raw=False)
            self.assertEqual(data, [])

    async def test_poll_with_updates(self) -> None:
        session_id = "test-session"
        session = HTTPSession(session_id=session_id, path="/")
        self.handler.sessions[session_id] = session

        # Queue an update
        self.handler.queue_update(session_id, {"type": "update", "html": "foo"})

        request = MockRequest.create(query_params={"session": session_id})
        response = await self.handler.poll(request)
        data = msgpack.unpackb(response.body, raw=False)

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["type"], "update")
        self.assertEqual(data[0]["html"], "foo")

    async def test_handle_event(self) -> None:
        session_id = "test-session"
        session = HTTPSession(session_id=session_id, path="/")
        # Create a real request for the page to avoid scope issues
        request = MockRequest.create()
        session.page = MockPage(request, {}, {})
        self.handler.sessions[session_id] = session

        request = MockRequest.create(
            body_data={"handler": "click", "data": {}}, headers={"X-PyWire-Session": session_id}
        )

        response = await self.handler.handle_event(request)
        data = msgpack.unpackb(response.body, raw=False)

        self.assertEqual(data["type"], "update")
        self.assertEqual(data["html"], "<div>HTTP Page</div>")


if __name__ == "__main__":
    unittest.main()
