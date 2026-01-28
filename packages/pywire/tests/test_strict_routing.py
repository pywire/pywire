import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

from pywire.runtime.app import PyWire
from starlette.requests import Request


class TestStrictRequirements(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.test_dir = tempfile.mkdtemp()
        self.pages_dir = Path(self.test_dir)
        (self.pages_dir / "index.pywire").write_text("<h1>Index</h1>")

        # Mock Starlette deps
        # Mock Starlette deps
        self.patches = [
            patch("starlette.applications.Starlette"),
            patch("pywire.runtime.app.HTTPTransportHandler"),
            patch("pywire.runtime.app.WebSocketHandler"),
            patch("pywire.runtime.webtransport_handler.WebTransportHandler"),
        ]
        for p in self.patches:
            p.start()

        # Mock get_loader
        self.mock_get_loader_patch = patch("pywire.runtime.loader.get_loader")
        self.mock_get_loader = self.mock_get_loader_patch.start()
        self.patches.append(self.mock_get_loader_patch)
        self.mock_loader_instance = MagicMock()
        self.mock_get_loader.return_value = self.mock_loader_instance

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.test_dir)

    def test_legacy_layout_ignored(self) -> None:
        """Confirm layout.pywire is IGNORED."""
        # Create layout.pywire
        (self.pages_dir / "layout.pywire").write_text("LayoutContent <slot />")

        app = PyWire(str(self.pages_dir))

        # app.loader should be a mock instance
        # We expect that for Strict Requirements, layout.pywire is NOT loaded as a layout.

        # In current code (before fix), it WILL be loaded. So this assertion should fail.

        layout_path = self.pages_dir / "layout.pywire"

        # Normalize path for comparison if needed, but Path objects compare well usually.
        # Check call args
        loaded_paths = []
        loader = cast(Any, app.loader)
        for call in loader.load.call_args_list:
            # call.args[0] is path
            loaded_paths.append(str(call.args[0]))

        self.assertNotIn(str(layout_path), loaded_paths, "layout.pywire should NOT be loaded")

    async def test_404_pywire_not_error_page(self) -> None:
        """Confirm 404.pywire is NOT used for error handling."""
        (self.pages_dir / "404.pywire").write_text("<h1>My Custom 404</h1>")

        app = PyWire(str(self.pages_dir))
        # Mock router match to NOT find anything for /nonexistent
        # But we need it to NOT find /404 when looking for error page

        # By default, app._handle_request calls router.match(path).
        # If not found, it calls router.match("/404").
        # We want to assert that it DOES NOT call match("/404") or even if it does,
        # it shouldn't use it?
        # Expectation: ONLY __error__.pywire works.
        # So match("/404") should NOT happen or be ignored in _handle_request.

        # If I can spy on router.match, I can verify calls.
        app.router = MagicMock()
        cast(Any, app.router).match.return_value = None  # Nothing found

        request = MagicMock(spec=Request)
        request.url.path = "/nonexistent"
        request.query_params = {}

        # Should call match("/nonexistent") -> None
        # Should THEN call match("/__error__")
        # Should NOT call match("/404")

        await app._handle_request(request)

        calls = cast(Any, app.router).match.call_args_list
        paths_checked = [c[0][0] for c in calls]

        self.assertIn("/nonexistent", paths_checked)
        self.assertNotIn("/404", paths_checked, "Should not look for /404")
        self.assertIn("/__error__", paths_checked, "Should look for /__error__")

    async def test_nested_error_ignored(self) -> None:
        """Confirm nested __error__.pywire is ignored."""
        (self.pages_dir / "sub").mkdir()
        (self.pages_dir / "sub" / "__error__.pywire").write_text("Nested Error")

        app = PyWire(str(self.pages_dir))

        # To verify it is ignored, we check existing routes
        # app.router.routes is a list of Route objects

        # We want to ensure NO route exists that maps to the nested error page.
        # Can we identify the page class? app.loader.load would have been called for it if loaded.

        # Let's check if loader loaded it first.
        # Nested __error__.pywire starts with _. _scan_directory skips files starting with _.
        # So it certainly should NOT be loaded via scan.
        # And _load_pages only explicit loads explicit root __error__.
        # So it should NOT be loaded at all.

        nested_error_path = self.pages_dir / "sub" / "__error__.pywire"
        loader = cast(Any, app.loader)
        loaded_paths = [str(call.args[0]) for call in loader.load.call_args_list]

        self.assertNotIn(
            str(nested_error_path), loaded_paths, "Nested __error__.pywire should NOT be loaded"
        )


if __name__ == "__main__":
    unittest.main()
