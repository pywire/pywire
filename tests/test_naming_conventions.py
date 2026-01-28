import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from pywire.runtime.app import PyWire
from starlette.requests import Request
from starlette.responses import Response


class TestNamingConventions(unittest.IsolatedAsyncioTestCase):
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
            # Setup router mock
            self.app.router = MagicMock()
            # Setup loader mock to avoid actual compilation
            self.app.loader = MagicMock()

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir)

    def test_layout_ignores_legacy(self) -> None:
        """Verify layout.pywire is IGNORED."""
        # Create both files
        (self.pages_dir / "layout.pywire").touch()
        (self.pages_dir / "__layout__.pywire").touch()
        (self.pages_dir / "index.pywire").touch()

        # Run scan
        self.app._scan_directory(self.pages_dir)

        # Verify loader.load was called for __layout__ (as implicit layout for index)
        # But NOT for layout.pywire

        expected_layout_path = self.pages_dir / "__layout__.pywire"
        legacy_layout_path = self.pages_dir / "layout.pywire"

        # Filter calls for layout loading
        loader = cast(Any, self.app.loader)
        layout_load_calls = [
            call for call in loader.load.call_args_list if call.args[0] == expected_layout_path
        ]

        legacy_load_calls = [
            call for call in loader.load.call_args_list if call.args[0] == legacy_layout_path
        ]

        self.assertTrue(len(layout_load_calls) > 0, "__layout__.pywire MUST be loaded")
        self.assertEqual(len(legacy_load_calls), 0, "layout.pywire MUST NOT be loaded")

        # Verify index page was loaded with implicit layout
        index_path = self.pages_dir / "index.pywire"
        loader = cast(Any, self.app.loader)
        loader.load.assert_any_call(index_path, implicit_layout=str(expected_layout_path.resolve()))

    def test_error_page_registration(self) -> None:
        """Verify __error__.pywire is registered at /__error__."""
        (self.pages_dir / "__error__.pywire").touch()

        # Mock load_pages behavior for error page
        # _load_pages explicitly checks for __error__.pywire
        self.app._load_pages()

        # Check explicit call in _load_pages manually
        # OR run _load_pages

        # Verify router add_route("/__error__", ...)
        router = cast(Any, self.app.router)
        router.add_route.assert_any_call("/__error__", unittest.mock.ANY)

    async def test_error_code_injection(self) -> None:
        """Verify fallback to /__error__ injects error_code."""
        # Setup router.match to simulate finding /__error__
        # Scenario: User requests /nonexistent -> 404

        # Mock page class
        mock_page_class = MagicMock()
        mock_page_instance = AsyncMock()
        mock_page_class.return_value = mock_page_instance
        mock_page_instance.render.return_value = Response("Error Content")

        # Router match returns: (PageClass, params, variant_name)
        # match("/404") -> None
        # match("/__error__") -> (PageClass, {}, 'main')

        def router_match_side_effect(path: str) -> Any:
            if path == "/404":
                return None
            if path == "/__error__":
                return (mock_page_class, {}, "main")
            return None

        cast(Any, self.app.router).match.side_effect = router_match_side_effect

        request = MagicMock(spec=Request)
        request.url.path = "/nonexistent"
        request.query_params = {}

        response = await self.app._handle_request(request)

        # Verify status code
        self.assertEqual(response.status_code, 404)

        # Verify error_code was set on page instance
        self.assertEqual(cast(Any, mock_page_instance).error_code, 404)


if __name__ == "__main__":
    unittest.main()
