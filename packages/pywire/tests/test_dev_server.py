"""Tests for dev_server._import_app error handling."""

import sys
import types
import pytest
from unittest.mock import patch


def _make_import_app():
    """Return a fresh reference to _import_app with sys.path isolated."""
    from pywire.runtime.dev_server import _import_app

    return _import_app


class TestImportApp:
    def test_success(self, tmp_path, monkeypatch):
        """Valid module:app string returns the app object."""
        mod = types.ModuleType("fake_app_mod")
        mod.app = object()
        monkeypatch.setitem(sys.modules, "fake_app_mod", mod)
        import_app = _make_import_app()
        result = import_app("fake_app_mod:app")
        assert result is mod.app

    def test_bad_module_raises_system_exit(self, monkeypatch):
        """Non-existent module triggers SystemExit(1)."""
        # Ensure the module isn't cached
        monkeypatch.delitem(sys.modules, "__nonexistent_pywire_mod__", raising=False)
        import_app = _make_import_app()
        with pytest.raises(SystemExit) as exc_info:
            import_app("__nonexistent_pywire_mod__:app")
        assert exc_info.value.code == 1

    def test_import_error_in_module_raises_system_exit(self, monkeypatch, tmp_path):
        """Module that raises ImportError during import triggers SystemExit(1)."""
        # Create a real Python file that imports a non-existent package
        mod_file = tmp_path / "bad_imports_mod.py"
        mod_file.write_text("import __totally_nonexistent_package_xyz__\n")
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.delitem(sys.modules, "bad_imports_mod", raising=False)

        import_app = _make_import_app()
        with pytest.raises(SystemExit) as exc_info:
            import_app("bad_imports_mod:app")
        assert exc_info.value.code == 1

    def test_bad_attribute_raises_system_exit(self, monkeypatch):
        """Valid module but missing attribute triggers SystemExit(1)."""
        mod = types.ModuleType("fake_app_mod_no_attr")
        monkeypatch.setitem(sys.modules, "fake_app_mod_no_attr", mod)
        import_app = _make_import_app()
        with pytest.raises(SystemExit) as exc_info:
            import_app("fake_app_mod_no_attr:missing_attr")
        assert exc_info.value.code == 1

    def test_bad_module_prints_message(self, monkeypatch, capsys):
        """ImportError prints a helpful message (via Rich console)."""
        monkeypatch.delitem(sys.modules, "__nonexistent_pywire_mod2__", raising=False)

        # Capture console.print output by patching the module-level console
        import pywire.runtime.dev_server as ds

        printed = []
        original_print = ds.console.print
        monkeypatch.setattr(ds.console, "print", lambda *a, **kw: printed.append(str(a)))

        import_app = _make_import_app()
        with pytest.raises(SystemExit):
            import_app("__nonexistent_pywire_mod2__:app")

        assert any("__nonexistent_pywire_mod2__" in msg for msg in printed)
