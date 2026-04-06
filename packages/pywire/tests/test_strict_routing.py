import pytest
import shutil
import tempfile
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

from pywire.runtime.app import PyWire
from starlette.requests import Request


class TestStrictRequirements:
    def setup_method(self) -> None:
        self.test_dir = tempfile.mkdtemp()
        self.pages_dir = Path(self.test_dir)
        (self.pages_dir / "index.wire").write_text("<h1>Index</h1>")

        # Mock Starlette deps
        self.patches = [
            patch("starlette.applications.Starlette"),
            patch("pywire.runtime.app.HTTPTransportHandler"),
            patch("pywire.runtime.app.WebSocketHandler"),
            patch("pywire.runtime.webtransport_handler.WebTransportHandler"),
        ]
        
        # Mock get_loader
        self.mock_get_loader_patch = patch("pywire.runtime.loader.get_loader")
        self.patches.append(self.mock_get_loader_patch)
        
        for p in self.patches:
            p.start()

        self.mock_get_loader = self.mock_get_loader_patch.target  # Note: this is a bit tricky with patch inside setup
        # Re-evaluating patch strategy: cleaner to just use patch inside setup_method
        
    def setup_method(self, method) -> None:
        self.test_dir = tempfile.mkdtemp()
        self.pages_dir = Path(self.test_dir)
        (self.pages_dir / "index.wire").write_text("<h1>Index</h1>")

        # Start patches
        self.p1 = patch("starlette.applications.Starlette").start()
        self.p2 = patch("pywire.runtime.app.HTTPTransportHandler").start()
        self.p3 = patch("pywire.runtime.app.WebSocketHandler").start()
        self.p4 = patch("pywire.runtime.webtransport_handler.WebTransportHandler").start()
        
        self.p5 = patch("pywire.runtime.loader.get_loader").start()
        self.mock_loader_instance = MagicMock()
        self.p5.return_value = self.mock_loader_instance

    def teardown_method(self, method) -> None:
        patch.stopall()
        shutil.rmtree(self.test_dir)

    def test_legacy_layout_ignored(self) -> None:
        """Confirm layout.wire is IGNORED."""
        # Create layout.wire
        (self.pages_dir / "layout.wire").write_text("LayoutContent <slot />")

        app = PyWire(str(self.pages_dir))

        layout_path = self.pages_dir / "layout.wire"

        # Check call args
        loaded_paths = []
        loader = cast(Any, app.loader)
        for call in loader.load.call_args_list:
            loaded_paths.append(str(call.args[0]))

        assert str(layout_path) not in loaded_paths, "layout.wire should NOT be loaded"

    @pytest.mark.asyncio
    async def test_404_pywire_not_error_page(self) -> None:
        """Confirm 404.wire is NOT used for error handling."""
        (self.pages_dir / "404.wire").write_text("<h1>My Custom 404</h1>")

        app = PyWire(str(self.pages_dir))
        app.router = MagicMock()
        cast(Any, app.router).match.return_value = None  # Nothing found

        request = MagicMock(spec=Request)
        request.url.path = "/nonexistent"
        request.query_params = {}

        await app._handle_request(request)

        calls = cast(Any, app.router).match.call_args_list
        paths_checked = [c[0][0] for c in calls]

        assert "/nonexistent" in paths_checked
        assert "/404" not in paths_checked, "Should not look for /404"
        assert "/__error__" in paths_checked, "Should look for /__error__"

    def test_nested_error_ignored(self) -> None:
        """Confirm nested __error__.wire is ignored."""
        (self.pages_dir / "sub").mkdir()
        (self.pages_dir / "sub" / "__error__.wire").write_text("Nested Error")

        app = PyWire(str(self.pages_dir))

        nested_error_path = self.pages_dir / "sub" / "__error__.wire"
        loader = cast(Any, app.loader)
        loaded_paths = [str(call.args[0]) for call in loader.load.call_args_list]

        assert str(nested_error_path) not in loaded_paths, "Nested __error__.wire should NOT be loaded"
