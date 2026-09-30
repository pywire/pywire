"""Tests for dev_server._import_app error handling."""

import sys
import types
import pytest


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

    def test_bad_module_prints_message(self, monkeypatch, caplog):
        """ImportError logs a helpful message."""
        import logging

        monkeypatch.delitem(sys.modules, "__nonexistent_pywire_mod2__", raising=False)

        import_app = _make_import_app()
        with caplog.at_level(logging.ERROR, logger="pywire.dev"):
            with pytest.raises(SystemExit):
                import_app("__nonexistent_pywire_mod2__:app")

        assert any("__nonexistent_pywire_mod2__" in r.message for r in caplog.records)


class TestResolveApps:
    """``pywire dev`` serves a PyWire app, or a host app with one mounted."""

    def _pywire(self, tmp_path):
        from pywire import PyWire

        pages = tmp_path / "pages"
        pages.mkdir()
        (pages / "index.wire").write_text("<p>hi</p>")
        return PyWire(pages_dir=str(pages))

    def test_pywire_app_is_served_itself(self, tmp_path):
        # Not its inner Starlette app: PyWire.__call__ applies base_path.
        from pywire.runtime.dev_server import _resolve_apps

        app = self._pywire(tmp_path)
        assert _resolve_apps(app) == (app, app)

    def test_host_app_is_served_whole(self, tmp_path):
        from starlette.applications import Starlette
        from starlette.routing import Mount

        from pywire.runtime.dev_server import _resolve_apps

        ui = self._pywire(tmp_path)
        host = Starlette(routes=[Mount("/", app=ui.as_asgi())])
        pywire_app, served = _resolve_apps(host)
        assert pywire_app is ui
        assert served is host

    def test_anything_else_exits(self):
        from pywire.runtime.dev_server import _resolve_apps

        with pytest.raises(SystemExit):
            _resolve_apps(object())
