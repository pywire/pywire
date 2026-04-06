import pytest
import asyncio
import json
import time
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


class TestAppExhaustive:
    def setup_method(self, method) -> None:
        self.temp_dir = TemporaryDirectory()
        self.pages_dir = Path(self.temp_dir.name).resolve()

        # Mock dependencies to avoid side effects during init
        self.loader_mock = patch("pywire.runtime.loader.get_loader").start()
        self.mock_loader = self.loader_mock.return_value

        self.ws_mock = patch("pywire.runtime.app.WebSocketHandler").start()
        self.mock_ws = self.ws_mock

        self.http_mock = patch("pywire.runtime.app.HTTPTransportHandler").start()
        self.mock_http = self.http_mock

        self.wt_mock = patch("pywire.runtime.webtransport_handler.WebTransportHandler").start()
        self.mock_wt = self.wt_mock

    def teardown_method(self, method) -> None:
        patch.stopall()
        self.temp_dir.cleanup()

    def test_app_init(self) -> None:
        app = PyWire(str(self.pages_dir))
        assert app.pages_dir == self.pages_dir
        assert app.router is not None
        self.mock_ws.assert_called_once_with(app)
        self.mock_http.assert_called_once_with(app)
        self.mock_wt.assert_called_once_with(app)

    def test_load_pages_recursive(self) -> None:
        # Create a nested structure
        (self.pages_dir / "sub").mkdir()
        (self.pages_dir / "index.wire").touch()
        (self.pages_dir / "about.wire").touch()
        (self.pages_dir / "sub" / "contact.wire").touch()
        (self.pages_dir / "sub" / "[id].wire").touch()
        (self.pages_dir / "layout.wire").touch()

        # Mock loader to return a class
        self.mock_loader.load.return_value = MockPage

        app = PyWire(str(self.pages_dir))

        # /
        match = app.router.match("/")
        assert match is not None
        assert match[0] == MockPage

        # /about
        match = app.router.match("/about")
        assert match is not None

        # /sub/contact
        match = app.router.match("/sub/contact")
        assert match is not None

        # /sub/123 (param)
        match = app.router.match("/sub/123")
        assert match is not None
        assert match[1] == {"id": "123"}

    @pytest.mark.asyncio
    async def test_handle_capabilities(self) -> None:
        app = PyWire(str(self.pages_dir))
        request = MagicMock(spec=Request)

        response = await app._handle_capabilities(request)

        assert isinstance(response, JSONResponse)
        data = json.loads(response.body)
        assert "transports" in data
        assert "websocket" in data["transports"]

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

    @pytest.mark.asyncio
    async def test_handle_upload_exception(self) -> None:
        app = PyWire(str(self.pages_dir))
        app.upload_tokens.add("tok")

        # Trigger an exception during await request.form()
        request = AsyncMock(spec=Request)
        request.headers = {"X-Upload-Token": "tok"}
        request.form.side_effect = Exception("Upload error")

        response = await app._handle_upload(request)
        assert response.status_code == 500

    def test_scan_directory_complex(self) -> None:
        # 1. Hidden file
        (self.pages_dir / "_hidden.wire").touch()
        # 2. Param directory
        (self.pages_dir / "[user_id]").mkdir()
        (self.pages_dir / "[user_id]" / "profile.wire").touch()
        # 3. Trailing slash case (index in sub)
        (self.pages_dir / "about").mkdir()
        (self.pages_dir / "about" / "index.wire").touch()
        # 4. Explicit !path routes
        (self.pages_dir / "custom.wire").touch()

        class ExplicitPage(MockPage):
            __routes__ = {"alt": "/my-custom-path"}

        def mock_load(path: Path, **kwargs: Any) -> Type[MockPage]:
            if "custom.wire" in str(path):
                return ExplicitPage
            return MockPage

        self.mock_loader.load.side_effect = mock_load
        app = PyWire(str(self.pages_dir))

        # Verify custom path
        match = app.router.match("/my-custom-path")
        assert match is not None

        # Verify trailing slash removal logic (internal check)
        match = app.router.match("/about")
        assert match is not None

    def test_scan_directory_load_fail(self) -> None:
        (self.pages_dir / "broken.wire").touch()
        # Fail load
        self.mock_loader.load.side_effect = Exception("Compile Error")

        with patch.object(PyWire, "_register_error_page") as mock_reg:
            PyWire(str(self.pages_dir))
            mock_reg.assert_called()

    @pytest.mark.asyncio
    async def test_handle_request_injection_no_body_tag(self) -> None:
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

            response = await app._handle_request(request)
            body = bytes(response.body).decode()
            assert "window.PYWIRE_CERT_HASH" in body
            assert body.endswith("</script>")

    @pytest.mark.asyncio
    async def test_handle_request_event_exception(self) -> None:
        app = PyWire(str(self.pages_dir))
        cast(Any, app.router).match = MagicMock(return_value=(MockPage, {}, "main"))

        with patch.object(MockPage, "handle_event", new_callable=AsyncMock) as mock_handle:
            mock_handle.side_effect = Exception("Event failure")

            headers = {"X-PyWire-Event": "click"}
            response = await self._async_test_request(app, method="POST", headers=headers)
            assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_handle_upload_security(self) -> None:
        app = PyWire(str(self.pages_dir))

        # 1. No token
        response = await self._async_test_upload(app, "")
        assert response.status_code == 403

        # 2. Invalid token
        response = await self._async_test_upload(app, "invalid")
        assert response.status_code == 403

        # 3. Valid token but too large
        app.upload_tokens.add("valid_token")
        response = await self._async_test_upload(app, "valid_token", content_length=20 * 1024 * 1024)
        assert response.status_code == 413

    @patch("pywire.runtime.app.upload_manager")
    @pytest.mark.asyncio
    async def test_handle_upload_success(self, mock_um: MagicMock) -> None:
        app = PyWire(str(self.pages_dir))
        app.upload_tokens.add("tok")
        mock_um.save.return_value = "upload_123"

        mock_file = MagicMock()
        mock_file.filename = "test.png"

        files = {"avatar": mock_file}

        response = await self._async_test_upload(app, "tok", files=files)

        assert response.status_code == 200
        data = json.loads(response.body)
        assert data["avatar"] == "upload_123"
        mock_um.save.assert_called_with(mock_file, max_size=app.max_upload_size)

    @patch("pywire.runtime.app.upload_manager")
    @pytest.mark.asyncio
    async def test_handle_upload_token_shared_between_app_instances(
        self, mock_um: MagicMock
    ) -> None:
        app_a = PyWire(str(self.pages_dir))
        app_b = PyWire(str(self.pages_dir))
        app_a._store_upload_token("shared_tok", None, time.time())
        mock_um.save.return_value = "upload_cross_worker"

        mock_file = MagicMock()
        mock_file.filename = "cross.png"
        files = {"avatar": mock_file}

        response = await self._async_test_upload(app_b, "shared_tok", files=files)
        assert response.status_code == 200
        data = json.loads(response.body)
        assert data["avatar"] == "upload_cross_worker"

    def test_reload_page(self) -> None:
        app = PyWire(str(self.pages_dir))
        path = self.pages_dir / "index.wire"
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
        file_path = self.pages_dir / "fail.wire"
        file_path.write_text("broken")

        with patch.object(app.router, "add_route") as mock_add_route:
            app._register_error_page(file_path, Exception("Parse Error"))

            # Should have registered at /fail
            mock_add_route.assert_called()
            args, _ = mock_add_route.call_args
            assert args[0] == "/fail"
            # The second arg is a BoundErrorPage class
            assert issubclass(args[1], BasePage)

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

    @pytest.mark.asyncio
    async def test_handle_request_event(self) -> None:
        app = PyWire(str(self.pages_dir))

        # Mock match
        cast(Any, app.router).match = MagicMock(return_value=(MockPage, {}, "main"))

        # Mock handle_event
        with patch.object(MockPage, "handle_event", new_callable=AsyncMock) as mock_handle:
            mock_handle.return_value = JSONResponse({"ok": True})

            headers = {"X-PyWire-Event": "click"}
            json_data = {"handler": "do_something", "data": {"val": 1}}

            response = await self._async_test_request(app, method="POST", headers=headers, json_data=json_data)

            assert response.status_code == 200
            mock_handle.assert_called_with("do_something", json_data)

    @pytest.mark.asyncio
    async def test_handle_request_injection(self) -> None:
        app = PyWire(str(self.pages_dir))
        cast(Any, app.router).match = MagicMock(return_value=(MockPage, {}, "main"))

        # Force __has_uploads__ on instance
        original_init = MockPage.__init__

        def mocked_init(self: MockPage, *args: Any, **kwargs: Any) -> None:
            cast(Any, self).__has_uploads__ = True
            original_init(self, *args, **kwargs)

        with patch.object(MockPage, "__init__", mocked_init):
            # Mock app state for cert hash
            request = AsyncMock(spec=Request)
            request.method = "GET"
            request.url.path = "/test"
            request.app.state.webtransport_cert_hash = [10, 20]
            request.query_params = {}

            response = await app._handle_request(request)

            body = bytes(response.body).decode()
            assert "window.PYWIRE_CERT_HASH = [10, 20]" in body
            assert 'name="pywire-upload-token"' in body
            assert len(app.upload_tokens) > 0

    @pytest.mark.asyncio
    async def test_asgi_call(self) -> None:
        app = PyWire(str(self.pages_dir))

        scope_wt = {"type": "webtransport"}
        scope_http = {"type": "http"}

        mock_send = AsyncMock()
        mock_receive = AsyncMock()

        # 1. WebTransport
        with patch.object(
            app.web_transport_handler, "handle", new_callable=AsyncMock
        ) as mock_wt_handle:
            await app(scope_wt, mock_receive, mock_send)
            mock_wt_handle.assert_called_once()

        # 2. Standard (Starlette)
        with patch.object(app, "app", new_callable=AsyncMock) as mock_starlette:
            await app(scope_http, mock_receive, mock_send)
            mock_starlette.assert_called_once()

    @pytest.mark.asyncio
    async def test_extensible_hooks(self) -> None:
        app = PyWire(str(self.pages_dir))

        # WS connect hook
        assert await app.on_ws_connect(None)

        # Get user hook
        mock_request = MagicMock()
        mock_request.scope = {"user": "alice"}
        mock_request.user = "alice"
        assert app.get_user(mock_request) == "alice"

        mock_request.scope = {}
        assert app.get_user(mock_request) is None
