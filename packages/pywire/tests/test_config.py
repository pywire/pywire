import shutil
import tempfile
import unittest
from pathlib import Path

from pywire.runtime.app import PyWire


class TestConfig(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = tempfile.mkdtemp()
        self.tmp_path = Path(self.test_dir).resolve()

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir)

    def test_default_config(self) -> None:
        # Should default to looking for 'pages' or 'src/pages' relative to cwd
        # But we can override it
        app = PyWire(pages_dir=str(self.tmp_path), debug=True)
        self.assertEqual(app.pages_dir, self.tmp_path)
        self.assertTrue(app.debug)
        self.assertTrue(app.path_based_routing)  # Default is True from user snippet

    def test_explicit_config(self) -> None:
        app = PyWire(
            pages_dir=str(self.tmp_path / "custom"),
            path_based_routing=False,
            enable_pjax=False,
            enable_webtransport=True,
        )
        self.assertEqual(app.pages_dir, self.tmp_path / "custom")
        self.assertFalse(app.path_based_routing)
        self.assertFalse(app.enable_pjax)
        self.assertTrue(app.enable_webtransport)

    def test_auto_discovery(self) -> None:
        # We need to mock _get_caller_dir to return a path in our temp dir
        # so that _get_project_root starts searching from there.
        from unittest.mock import patch

        with patch("pywire.runtime.app.PyWire._get_caller_dir", return_value=self.tmp_path):
            (self.tmp_path / "src" / "pages").mkdir(parents=True)
            # Create a project marker so it knows this is the root
            (self.tmp_path / "pyproject.toml").touch()
            
            app = PyWire(pages_dir=None)
            self.assertEqual(app.pages_dir, self.tmp_path / "src" / "pages")

    def test_auto_discovery_root(self) -> None:
        # Test finding 'pages' in root
        from unittest.mock import patch

        with patch("pywire.runtime.app.PyWire._get_caller_dir", return_value=self.tmp_path):
            (self.tmp_path / "pages").mkdir()
            # Create a project marker so it knows this is the root
            (self.tmp_path / "pyproject.toml").touch()

            app = PyWire(pages_dir=None)
            self.assertEqual(app.pages_dir, self.tmp_path / "pages")
            
    def test_project_root_fallback(self) -> None:
        # If no marker found, project root should be caller dir
        from unittest.mock import patch
        
        # Ensure no markers exist in tmp_path or parents (within reason for test)
        # We assume tmp_path is clean.
        
        with patch("pywire.runtime.app.PyWire._get_caller_dir", return_value=self.tmp_path):
            # No pyproject.toml created
            (self.tmp_path / "pages").mkdir()
            
            # Should find pages relative to caller_dir (which becomes project_root)
            app = PyWire(pages_dir=None)
            self.assertEqual(app.pages_dir, self.tmp_path / "pages")


if __name__ == "__main__":
    unittest.main()
