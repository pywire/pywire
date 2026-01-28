import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pywire.runtime.app import PyWire
from pywire.runtime.page import BasePage
from starlette.requests import Request


class TestAppRuntime(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.test_dir = tempfile.mkdtemp()
        self.pages_dir = Path(self.test_dir).resolve()
        # Mock Starlette to avoid actual server setup
        with (
            patch("starlette.applications.Starlette"),
            patch("pywire.runtime.loader.PageLoader"),
            patch("pywire.runtime.app.HTTPTransportHandler"),
            patch("pywire.runtime.app.WebSocketHandler"),
            patch("pywire.runtime.webtransport_handler.WebTransportHandler"),
        ):
            self.app = PyWire(str(self.pages_dir))

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir)

    async def test_handle_capabilities(self) -> None:
        request = MagicMock(spec=Request)
        response = await self.app._handle_capabilities(request)
        import json

        data = json.loads(response.body)
        self.assertIn("transports", data)
        self.assertEqual(data["version"], "0.0.1")

    def test_scan_directory_routing(self) -> None:
        # Create a nested structure
        (self.pages_dir / "index.pywire").touch()
        users = self.pages_dir / "users"
        users.mkdir()
        (users / "[id].pywire").touch()

        # Mock loader to return dummy classes
        with patch.object(self.app.loader, "load", return_value=type("Page", (BasePage,), {})):
            self.app.router = MagicMock()
            self.app._scan_directory(self.pages_dir)

        # Verify routes were added
        # index -> /
        # users/[id].pywire -> /users/{id}
        self.app.router.add_route.assert_any_call("/", unittest.mock.ANY)
        self.app.router.add_route.assert_any_call("/users/{id}", unittest.mock.ANY)

    @patch("pywire.runtime.app.upload_manager")
    async def test_handle_upload_invalid_token(self, mock_upload: MagicMock) -> None:
        request = MagicMock(spec=Request)
        request.headers = {"X-Upload-Token": "invalid"}
        response = await self.app._handle_upload(request)
        self.assertEqual(response.status_code, 403)

    @patch("pywire.runtime.app.upload_manager")
    async def test_handle_upload_success(self, mock_upload: MagicMock) -> None:
        self.app.upload_tokens.add("valid-token")
        mock_upload.save.return_value = "upload-123"

        request = AsyncMock(spec=Request)
        request.headers = {"X-Upload-Token": "valid-token"}

        # Mock form data
        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        # request.form must be an async method returning the dict
        request.form = AsyncMock(return_value={"file": mock_file})

        response = await self.app._handle_upload(request)
        self.assertEqual(response.status_code, 200)
        import json

        data = json.loads(response.body)
        self.assertEqual(data["file"], "upload-123")

    def test_register_error_page(self) -> None:
        self.app.router = MagicMock()
        file_path = self.pages_dir / "broken.pywire"
        file_path.write_text("!path '/broken'\nINVALID PYTHON")

        self.app._register_error_page(file_path, Exception("Parse error"))

        # Should register the custom route if found via regex
        self.app.router.add_route.assert_any_call("/broken", unittest.mock.ANY)

    def test_reload_page_implicit_routing(self) -> None:
        # Create a page that relies on implicit routing
        page_path = self.pages_dir / "implicit.pywire"
        page_path.write_text("<h1>Implicit</h1>")

        # Mock loader to return a class without explicit routes
        page_class = type("Page", (BasePage,), {})
        with (
            patch.object(self.app.loader, "load", return_value=page_class),
            patch.object(
                self.app.loader, "invalidate_cache", return_value={str(page_path.resolve())}
            ),
        ):
            # Mock router
            self.app.router = MagicMock()
            self.app.router.routes = []

            # Enable path based routing
            self.app.path_based_routing = True

            # Call reload_page
            self.app.reload_page(page_path)

        # Verify that add_route was called with the implicit path
        # /implicit.pywire -> /implicit
        self.app.router.add_route.assert_called_with("/implicit", page_class)


if __name__ == "__main__":
    unittest.main()
