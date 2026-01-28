import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from pywire.runtime.app import PyWire
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class TestAppAdvanced(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.pages_dir = Path("/tmp/empty_pages").resolve()
        self.pages_dir.mkdir(exist_ok=True)
        with (
            patch("starlette.applications.Starlette"),
            patch("pywire.runtime.loader.PageLoader"),
            patch("pywire.runtime.app.HTTPTransportHandler"),
            patch("pywire.runtime.app.WebSocketHandler"),
            patch("pywire.runtime.webtransport_handler.WebTransportHandler"),
        ):
            self.app = PyWire(str(self.pages_dir))
            self.app.router = MagicMock()

    async def test_handle_request_post_event(self) -> None:
        # Mocking a POST request with X-PyWire-Event header
        request = AsyncMock(spec=Request)
        request.method = "POST"
        request.headers = {"X-PyWire-Event": "click"}
        request.url.path = "/test"
        request.json.return_value = {"handler": "save", "data": {}}

        page_class = MagicMock()
        cast(Any, self.app.router).match.return_value = (page_class, {}, "main")

        # Mock page instance
        page_inst = MagicMock()
        page_inst.handle_event = AsyncMock(return_value=JSONResponse({"success": True}))
        page_class.return_value = page_inst

        response = await self.app._handle_request(request)
        self.assertEqual(response.status_code, 200)
        page_inst.handle_event.assert_called_once_with("save", {"handler": "save", "data": {}})

    async def test_handle_request_injection(self) -> None:
        # Test injection of scripts/meta tags
        request = AsyncMock(spec=Request)
        request.method = "GET"
        request.url.path = "/test"
        request.app.state.webtransport_cert_hash = [1, 2, 3]

        page_class = MagicMock()
        cast(Any, self.app.router).match.return_value = (page_class, {}, "main")

        # Mock page instance with upload needs
        page_inst = MagicMock()
        page_inst.__has_uploads__ = True
        page_inst.render = AsyncMock(
            return_value=Response("<html><body></body></html>", media_type="text/html")
        )
        page_class.return_value = page_inst

        response = await self.app._handle_request(request)
        body = bytes(response.body).decode()
        self.assertIn("window.PYWIRE_CERT_HASH", body)
        self.assertIn('name="pywire-upload-token"', body)


if __name__ == "__main__":
    unittest.main()
