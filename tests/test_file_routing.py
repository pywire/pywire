# Helper to mock modules for tests
import importlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, List, Optional, Tuple, Type, cast
from unittest.mock import MagicMock


def mock_modules(mapping: dict) -> dict:
    original_modules = {}
    for name, mock in mapping.items():
        if name in sys.modules:
            original_modules[name] = sys.modules[name]
        sys.modules[name] = mock
    return original_modules


def restore_modules(original_modules: dict, mapping: dict) -> None:
    for name in mapping:
        if name in original_modules:
            sys.modules[name] = original_modules[name]
        else:
            del sys.modules[name]


# Mock base page for loader
class MockPage:
    LAYOUT_ID = None
    pass


class MockLoader:
    def __init__(self) -> None:
        self.loaded: List[Tuple[Path, Optional[str]]] = []

    def load(
        self, path: Path, use_cache: bool = True, implicit_layout: str | None = None
    ) -> type[MockPage]:
        self.loaded.append((path, implicit_layout))

        # Return a mock class with identifying info
        class Page(MockPage):
            __file_path__ = str(path)
            # Simulate layout directive effect if implicit layout provided
            pass

        return Page

    def invalidate_cache(self, path: Optional[Path] = None) -> None:
        pass


class TestFileRouting(unittest.TestCase):
    def setUp(self) -> None:
        # Setup mocks
        self.mock_starlette = MagicMock()
        self.mock_jinja2 = MagicMock()
        self.mock_lxml = MagicMock()

        self.mocks = {
            "starlette": self.mock_starlette,
            "starlette.requests": self.mock_starlette,
            "starlette.responses": self.mock_starlette,
            "starlette.routing": self.mock_starlette,
            "starlette.staticfiles": self.mock_starlette,
            "starlette.applications": self.mock_starlette,
            "starlette.websockets": self.mock_starlette,
            "starlette.datastructures": self.mock_starlette,
            "starlette.types": self.mock_starlette,
            "starlette.exceptions": self.mock_starlette,
            "starlette.middleware": self.mock_starlette,
            "jinja2": self.mock_jinja2,
            "lxml": self.mock_lxml,
            "lxml.html": self.mock_lxml,
            "lxml.etree": self.mock_lxml,
        }
        self.original_modules = mock_modules(self.mocks)

        from pywire.runtime.app import PyWire
        from pywire.runtime.router import Router

        self.test_dir = tempfile.mkdtemp()
        self.tmp_path = Path(self.test_dir)

        self.app = PyWire(str(self.tmp_path))
        self.app.loader = cast(Any, MockLoader())
        self.app.router = Router()

    def expected_mounts(self, expected: List[str]) -> None:
        pass

    def tearDown(self) -> None:
        from pywire.runtime import app as app_mod
        from pywire.runtime import loader as loader_mod
        from pywire.runtime import router as router_mod

        shutil.rmtree(self.test_dir)
        restore_modules(self.original_modules, self.mocks)
        importlib.reload(app_mod)
        importlib.reload(router_mod)
        importlib.reload(loader_mod)

    def test_scan_simple_structure(self) -> None:
        """Test standard file structure scanning."""
        # Create pages
        (self.tmp_path / "index.pywire").touch()
        (self.tmp_path / "about.pywire").touch()

        self.app._scan_directory(self.tmp_path)

        # Check routes
        routes = {r.pattern: r for r in self.app.router.routes}
        # Check regex pattern for root since / is often compiled to regex
        root_patterns = [r.regex.pattern for r in self.app.router.routes if r.pattern == "/"]
        self.assertTrue(any("^/$" in p for p in root_patterns) or "/" in routes)
        self.assertIn("/about", routes)

    def test_scan_nested_structure(self) -> None:
        """Test nested directories and params."""
        (self.tmp_path / "index.pywire").touch()

        users = self.tmp_path / "users"
        users.mkdir()
        (users / "index.pywire").touch()
        (users / "[id].pywire").touch()

        posts = self.tmp_path / "posts"
        posts.mkdir()
        (posts / "[slug]").mkdir()
        (posts / "[slug]" / "index.pywire").touch()

        self.app._scan_directory(self.tmp_path)

        routes = {r.pattern: r for r in self.app.router.routes}

        self.assertIn("/", routes)
        self.assertIn("/users", routes)  # users/index.pywire -> /users/

        # [id].pywire -> /users/{id}
        self.assertIn("/users/{id}", routes)

        # posts/[slug]/index.pywire -> /posts/{slug}/
        # Normalized by router might be different
        self.assertIn("/posts/{slug}", routes)

    def test_scan_layouts(self) -> None:
        """Test layout discovery and injection."""
        layout = self.tmp_path / "__layout__.pywire"
        layout.touch()

        (self.tmp_path / "index.pywire").touch()

        sub = self.tmp_path / "sub"
        sub.mkdir()
        (sub / "page.pywire").touch()

        # Sub layout
        sub_layout = sub / "__layout__.pywire"
        sub_layout.touch()

        self.app._scan_directory(self.tmp_path)

        # Check loading calls
        loader = cast(Any, self.app.loader)
        loaded = loader.loaded

        # 1. Root layout should be loaded first (implicit_layout=None)
        # Loader called with (path, implicit_layout)

        # Normalize paths for comparison
        # On macOS /var is link to /private/var. resolve() resolves it.
        # But we need to be consistent.
        def norm(p: Path) -> str:
            return str(p.resolve())

        loaded_normalized = [(norm(p), layout) for p, layout in loaded]

        # Root layout loading
        self.assertIn((norm(layout), None), loaded_normalized)

        # Index should have root layout
        self.assertIn((norm(self.tmp_path / "index.pywire"), norm(layout)), loaded_normalized)

        # Sub layout should be loaded with root layout as implicit!
        self.assertIn((norm(sub_layout), norm(layout)), loaded_normalized)

        # Sub page should have sub layout
        self.assertIn((norm(sub / "page.pywire"), norm(sub_layout)), loaded_normalized)

    def test_disable_path_based_routing(self) -> None:
        """Test that path_based_routing=False ignores implicit routes but keeps explicit ones."""
        # Re-init app with path_based_routing=False
        from pywire.runtime.app import PyWire

        self.app = PyWire(str(self.tmp_path), path_based_routing=False)
        self.app.loader = cast(Any, MockLoader())

        # 1. Implicit page (should be IGNORED)
        (self.tmp_path / "implicit.pywire").touch()

        # 2. Explicit page (should be KEPT)
        explicit = self.tmp_path / "explicit.pywire"
        explicit.touch()

        # We need MockLoader to return a class with __routes__ for the explicit one
        # This requires a bit of mocking magic since MockLoader is simple
        original_load = cast(Any, self.app.loader).load

        def mock_load(
            path: Path, use_cache: bool = True, implicit_layout: str | None = None
        ) -> Type[MockPage]:
            cls = original_load(path, use_cache=use_cache, implicit_layout=implicit_layout)
            if path.name == "explicit.pywire":
                cast(Any, cls).__routes__ = {"main": "/explicit"}
            return cast(Type[MockPage], cls)

        cast(Any, self.app.loader).load = mock_load

        self.app._scan_directory(self.tmp_path)

        routes = {r.pattern for r in self.app.router.routes}
        self.assertNotIn("/implicit", routes)
        self.assertIn("/explicit", routes)

    def test_enable_path_based_routing(self) -> None:
        """Test that path_based_routing=True (default) enables implicit routes."""
        # Re-init app with path_based_routing=True
        from pywire.runtime.app import PyWire

        self.app = PyWire(str(self.tmp_path), path_based_routing=True)
        self.app.loader = cast(Any, MockLoader())

        (self.tmp_path / "implicit.pywire").touch()

        self.app._scan_directory(self.tmp_path)

        routes = {r.pattern for r in self.app.router.routes}
        self.assertIn("/implicit", routes)


if __name__ == "__main__":
    unittest.main()
