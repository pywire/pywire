import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, Optional, Type, cast
from unittest.mock import AsyncMock, MagicMock, patch

from pywire.runtime.app import PyWire
from pywire.runtime.page import BasePage
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class MockPage(BasePage):
    async def render(self, init: bool = True) -> Response:
        return Response("<html><body></body></html>", media_type="text/html")


class TestAppExhaustive(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.pages_dir = Path(self.temp_dir.name).resolve()

        # Mock dependencies to avoid side effects during init
        self.loader_patcher = patch("pywire.runtime.loader.get_loader")
        self.mock_loader = self.loader_patcher.start().return_value

        self.ws_patcher = patch("pywire.runtime.app.WebSocketHandler")
        self.mock_ws = self.ws_patcher.start()

        self.http_patcher = patch("pywire.runtime.app.HTTPTransportHandler")
        self.mock_http = self.http_patcher.start()

        self.wt_patcher = patch("pywire.runtime.webtransport_handler.WebTransportHandler")
        self.mock_wt = self.wt_patcher.start()

    def tearDown(self) -> None:
        self.wt_patcher.stop()
        self.http_patcher.stop()
        self.ws_patcher.stop()
        self.loader_patcher.stop()
        self.temp_dir.cleanup()

    def test_app_init(self) -> None:
        app = PyWire(str(self.pages_dir))
        self.assertEqual(app.pages_dir, self.pages_dir)
        self.assertIsNotNone(app.router)
        self.mock_ws.assert_called_once_with(app)
        self.mock_http.assert_called_once_with(app)
        self.mock_wt.assert_called_once_with(app)

    def test_load_pages_recursive(self) -> None:
        # Create a nested structure
        (self.pages_dir / "sub").mkdir()
        (self.pages_dir / "index.pywire").touch()
        (self.pages_dir / "about.pywire").touch()
        (self.pages_dir / "sub" / "contact.pywire").touch()
        (self.pages_dir / "sub" / "[id].pywire").touch()
        (self.pages_dir / "layout.pywire").touch()

        # Mock loader to return a class
        self.mock_loader.load.return_value = MockPage

        app = PyWire(str(self.pages_dir))

        # Check if routes were registered correctly
        # We can't easily check app.router.routes because they are internal,
        # but we can try matching.

        # /
        match = app.router.match("/")
        assert match is not None
        self.assertEqual(match[0], MockPage)

        # /about
        match = app.router.match("/about")
        self.assertIsNotNone(match)

        # /sub/contact
        match = app.router.match("/sub/contact")
        self.assertIsNotNone(match)

        # /sub/123 (param)
        match = app.router.match("/sub/123")
        assert match is not None
        self.assertEqual(match[1], {"id": "123"})

    def test_handle_capabilities(self) -> None:
        app = PyWire(str(self.pages_dir))
        request = MagicMock(spec=Request)

        # Run async method
        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(app._handle_capabilities(request))

        self.assertIsInstance(response, JSONResponse)
        data = json.loads(response.body)
        self.assertIn("transports", data)
        self.assertIn("websocket", data["transports"])

    async def _async_test_upload(
        self,
        app: PyWire,
        token: str,
        content_length: int = 100,
        files: Optional[Dict[str, Any]] = None,
    ) -> Any:
        request = AsyncMock(spec=Request)
        request.headers = {"X-Upload-Token": token, "content-length": str(content_length)}
        request.form = AsyncMock(return_value=files or {})
        request.url = MagicMock()
        return await app._handle_upload(request)

    def test_handle_upload_exception(self) -> None:
        app = PyWire(str(self.pages_dir))
        app.upload_tokens.add("tok")
        loop = asyncio.get_event_loop()

        # Trigger an exception during await request.form()
        request = AsyncMock(spec=Request)
        request.headers = {"X-Upload-Token": "tok"}
        request.form.side_effect = Exception("Upload error")

        response = loop.run_until_complete(app._handle_upload(request))
        self.assertEqual(response.status_code, 500)

    def test_scan_directory_complex(self) -> None:
        # 1. Hidden file
        (self.pages_dir / "_hidden.pywire").touch()
        # 2. Param directory
        (self.pages_dir / "[user_id]").mkdir()
        (self.pages_dir / "[user_id]" / "profile.pywire").touch()
        # 3. Trailing slash case (index in sub)
        (self.pages_dir / "about").mkdir()
        (self.pages_dir / "about" / "index.pywire").touch()
        # 4. Explicit !path routes
        (self.pages_dir / "custom.pywire").touch()

        class ExplicitPage(MockPage):
            __routes__ = {"alt": "/my-custom-path"}

        def mock_load(path: Path, **kwargs: Any) -> Type[MockPage]:
            if "custom.pywire" in str(path):
                return ExplicitPage
            return MockPage

        self.mock_loader.load.side_effect = mock_load
        app = PyWire(str(self.pages_dir))

        # Verify custom path
        match = app.router.match("/my-custom-path")
        self.assertIsNotNone(match)

        # Verify trailing slash removal logic (internal check)
        match = app.router.match("/about")
        self.assertIsNotNone(match)

    def test_scan_directory_load_fail(self) -> None:
        (self.pages_dir / "broken.pywire").touch()
        # Fail load
        self.mock_loader.load.side_effect = Exception("Compile Error")

        with patch.object(PyWire, "_register_error_page") as mock_reg:
            PyWire(str(self.pages_dir))
            mock_reg.assert_called()

    def test_handle_request_injection_no_body_tag(self) -> None:
        app = PyWire(str(self.pages_dir))
        cast(Any, app.router).match = MagicMock(return_value=(MockPage, {}, "main"))

        # Mock page to return body without </body>
        with patch.object(MockPage, "render", new_callable=AsyncMock) as mock_render:
            mock_render.return_value = Response("Hello", media_type="text/html")

            request = AsyncMock(spec=Request)
            request.method = "GET"
            request.url.path = "/test"
            request.app.state.webtransport_cert_hash = [1]
            request.query_params = {}

            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(app._handle_request(request))
            body = bytes(response.body).decode()
            self.assertIn("window.PYWIRE_CERT_HASH", body)
            self.assertTrue(body.endswith("</script>"))

    def test_handle_request_event_exception(self) -> None:
        app = PyWire(str(self.pages_dir))
        cast(Any, app.router).match = MagicMock(return_value=(MockPage, {}, "main"))

        with patch.object(MockPage, "handle_event", new_callable=AsyncMock) as mock_handle:
            mock_handle.side_effect = Exception("Event failure")

            headers = {"X-PyWire-Event": "click"}
            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(
                self._async_test_request(app, method="POST", headers=headers)
            )
            self.assertEqual(response.status_code, 500)

    def test_handle_upload_security(self) -> None:
        app = PyWire(str(self.pages_dir))
        loop = asyncio.get_event_loop()

        # 1. No token
        response = loop.run_until_complete(self._async_test_upload(app, ""))
        self.assertEqual(response.status_code, 403)

        # 2. Invalid token
        response = loop.run_until_complete(self._async_test_upload(app, "invalid"))
        self.assertEqual(response.status_code, 403)

        # 3. Valid token but too large
        app.upload_tokens.add("valid_token")
        response = loop.run_until_complete(
            self._async_test_upload(app, "valid_token", content_length=20 * 1024 * 1024)
        )
        self.assertEqual(response.status_code, 413)

    @patch("pywire.runtime.app.upload_manager")
    def test_handle_upload_success(self, mock_um: MagicMock) -> None:
        app = PyWire(str(self.pages_dir))
        app.upload_tokens.add("tok")
        mock_um.save.return_value = "upload_123"

        mock_file = MagicMock()
        mock_file.filename = "test.png"

        files = {"avatar": mock_file}

        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(self._async_test_upload(app, "tok", files=files))

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.body)
        self.assertEqual(data["avatar"], "upload_123")
        mock_um.save.assert_called_with(mock_file)

    def test_reload_page(self) -> None:
        app = PyWire(str(self.pages_dir))
        path = self.pages_dir / "index.pywire"
        path.touch()

        with (
            patch.object(app.router, "remove_routes_for_file") as mock_remove,
            patch.object(app.router, "add_page") as mock_add,
        ):
            self.mock_loader.load.return_value = MockPage
            self.mock_loader.invalidate_cache.return_value = {str(path.resolve())}
            app.reload_page(path)

            self.mock_loader.invalidate_cache.assert_called_with(path)
            mock_remove.assert_called_with(str(path.resolve()))
            mock_add.assert_called_with(MockPage)

    def test_register_error_page(self) -> None:
        app = PyWire(str(self.pages_dir))
        file_path = self.pages_dir / "fail.pywire"
        file_path.write_text("broken")

        with patch.object(app.router, "add_route") as mock_add_route:
            app._register_error_page(file_path, Exception("Parse Error"))

            # Should have registered at /fail
            mock_add_route.assert_called()
            args, _ = mock_add_route.call_args
            self.assertEqual(args[0], "/fail")
            # The second arg is a BoundErrorPage class
            self.assertTrue(issubclass(args[1], BasePage))

    async def _async_test_request(
        self,
        app: PyWire,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        path: str = "/test",
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Any:
        request = AsyncMock(spec=Request)
        request.method = method
        request.url.path = path
        request.headers = headers or {}
        request.json.return_value = json_data or {}
        request.query_params = {}
        request.app.state = MagicMock()
        return await app._handle_request(request)

    def test_handle_request_event(self) -> None:
        app = PyWire(str(self.pages_dir))

        # Mock match
        cast(Any, app.router).match = MagicMock(return_value=(MockPage, {}, "main"))

        # Mock handle_event
        with patch.object(MockPage, "handle_event", new_callable=AsyncMock) as mock_handle:
            mock_handle.return_value = JSONResponse({"ok": True})

            headers = {"X-PyWire-Event": "click"}
            json_data = {"handler": "do_something", "data": {"val": 1}}

            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(
                self._async_test_request(app, method="POST", headers=headers, json_data=json_data)
            )

            self.assertEqual(response.status_code, 200)
            mock_handle.assert_called_with("do_something", json_data)

    def test_handle_request_injection(self) -> None:
        app = PyWire(str(self.pages_dir))
        cast(Any, app.router).match = MagicMock(return_value=(MockPage, {}, "main"))

        # Force __has_uploads__ on instance
        original_init = MockPage.__init__

        def mocked_init(self: MockPage, *args: Any, **kwargs: Any) -> None:
            cast(Any, self).__has_uploads__ = True
            original_init(self, *args, **kwargs)

        with patch.object(MockPage, "__init__", mocked_init):
            loop = asyncio.get_event_loop()
            # Mock app state for cert hash
            request = AsyncMock(spec=Request)
            request.method = "GET"
            request.url.path = "/test"
            request.app.state.webtransport_cert_hash = [10, 20]
            request.query_params = {}

            response = loop.run_until_complete(app._handle_request(request))

            body = bytes(response.body).decode()
            self.assertIn("window.PYWIRE_CERT_HASH = [10, 20]", body)
            self.assertIn('name="pywire-upload-token"', body)
            self.assertTrue(len(app.upload_tokens) > 0)

    def test_asgi_call(self) -> None:
        app = PyWire(str(self.pages_dir))

        scope_wt = {"type": "webtransport"}
        scope_http = {"type": "http"}

        mock_send = AsyncMock()
        mock_receive = AsyncMock()

        loop = asyncio.get_event_loop()

        # 1. WebTransport
        with patch.object(
            app.web_transport_handler, "handle", new_callable=AsyncMock
        ) as mock_wt_handle:
            loop.run_until_complete(app(scope_wt, mock_receive, mock_send))
            mock_wt_handle.assert_called_once()

        # 2. Standard (Starlette)
        with patch.object(app, "app", new_callable=AsyncMock) as mock_starlette:
            loop.run_until_complete(app(scope_http, mock_receive, mock_send))
            mock_starlette.assert_called_once()

    def test_extensible_hooks(self) -> None:
        app = PyWire(str(self.pages_dir))
        loop = asyncio.get_event_loop()

        # WS connect hook
        self.assertTrue(loop.run_until_complete(app.on_ws_connect(None)))

        # Get user hook
        mock_request = MagicMock()
        mock_request.scope = {"user": "alice"}
        mock_request.user = "alice"
        self.assertEqual(app.get_user(mock_request), "alice")

        mock_request.scope = {}
        self.assertIsNone(app.get_user(mock_request))


if __name__ == "__main__":
    unittest.main()
