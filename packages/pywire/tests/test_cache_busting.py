"""Tests for static asset cache busting via version query parameter."""

from pywire import __version__
from pywire.runtime.app import PyWire


def test_cache_busting_prod_url(tmp_path) -> None:
    """Production script URL includes ?v= with the package version."""
    (tmp_path / "pages").mkdir()
    app = PyWire(debug=False, pages_dir=str(tmp_path / "pages"))
    app._is_dev_mode = False

    url = app._get_client_script_url()
    assert url == f"/_pywire/static/pywire.core.min.js?v={__version__}"
    assert "?v=" in url


def test_cache_busting_dev_url(tmp_path) -> None:
    """Dev script URL uses the bundle's mtime so rebuilds bust the cache."""
    (tmp_path / "pages").mkdir()
    app = PyWire(debug=True, pages_dir=str(tmp_path / "pages"))
    app._is_dev_mode = True

    url = app._get_client_script_url()
    assert url.startswith("/_pywire/static/pywire.dev.min.js?v=")
    # Dev buster is an int mtime — not the package version string.
    buster = url.split("?v=")[1]
    assert buster.isdigit()


def test_cache_busting_version_not_empty(tmp_path) -> None:
    """The version string used for cache busting is not empty or 'unknown'."""
    (tmp_path / "pages").mkdir()
    app = PyWire(pages_dir=str(tmp_path / "pages"))

    url = app._get_client_script_url()
    version_param = url.split("?v=")[1]
    assert version_param
    assert version_param != "unknown"
