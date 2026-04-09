"""Tests for user static asset fingerprinting."""

import hashlib
import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from pywire.compiler.build import fingerprint_static_assets
from pywire.runtime.page import BasePage


def _make_page(
    *,
    static_dir: Path | None = None,
    static_url_path: str = "/static",
    is_dev_mode: bool = False,
    asset_hash_cache: dict | None = None,
    asset_manifest: dict | None = None,
    asset_warned_missing: set | None = None,
) -> BasePage:
    """Create a minimal BasePage with a mock app for testing asset()."""
    pywire_app = SimpleNamespace(
        static_dir=static_dir,
        static_url_path=static_url_path,
        _is_dev_mode=is_dev_mode,
        _asset_hash_cache=asset_hash_cache if asset_hash_cache is not None else {},
        _asset_manifest=asset_manifest,
        _asset_warned_missing=asset_warned_missing
        if asset_warned_missing is not None
        else set(),
    )
    app_state = SimpleNamespace(pywire=pywire_app)
    app = SimpleNamespace(state=app_state)
    request = MagicMock()
    request.app = app

    page = BasePage.__new__(BasePage)
    page.request = request
    return page


class TestAssetDevMode:
    def test_uses_mtime_timestamp(self, tmp_path: Path) -> None:
        static = tmp_path / "static"
        static.mkdir()
        css = static / "style.css"
        css.write_text("body { color: red; }")

        page = _make_page(static_dir=static, is_dev_mode=True)
        result = page.asset("style.css")

        mtime = int(os.path.getmtime(css))
        assert result == f"/static/style.css?v={mtime}"

    def test_no_caching(self, tmp_path: Path) -> None:
        static = tmp_path / "static"
        static.mkdir()
        css = static / "style.css"
        css.write_text("v1")

        page = _make_page(static_dir=static, is_dev_mode=True)
        result1 = page.asset("style.css")

        # Modify file (bump mtime)
        os.utime(css, (css.stat().st_atime, css.stat().st_mtime + 1))
        result2 = page.asset("style.css")

        assert result1 != result2

    def test_missing_file_returns_plain_url(self, tmp_path: Path) -> None:
        static = tmp_path / "static"
        static.mkdir()

        page = _make_page(static_dir=static, is_dev_mode=True)
        result = page.asset("nonexistent.css")

        assert result == "/static/nonexistent.css"


class TestAssetProdNoManifest:
    def test_uses_content_hash(self, tmp_path: Path) -> None:
        static = tmp_path / "static"
        static.mkdir()
        css = static / "style.css"
        css.write_text("body { color: red; }")

        page = _make_page(static_dir=static)
        result = page.asset("style.css")

        expected_hash = hashlib.md5(css.read_bytes()).hexdigest()[:12]
        assert result == f"/static/style.css?v={expected_hash}"

    def test_caches_hash(self, tmp_path: Path) -> None:
        static = tmp_path / "static"
        static.mkdir()
        css = static / "style.css"
        css.write_text("body { color: red; }")

        cache: dict = {}
        page = _make_page(static_dir=static, asset_hash_cache=cache)
        page.asset("style.css")

        # Cache should now have the entry
        assert "style.css" in cache

        # Second call should use cache (even if file changes)
        css.write_text("body { color: blue; }")
        result = page.asset("style.css")
        # Should still have old hash from cache
        old_hash = cache["style.css"]
        assert result == f"/static/style.css?v={old_hash}"

    def test_missing_file_returns_plain_url(self, tmp_path: Path) -> None:
        static = tmp_path / "static"
        static.mkdir()

        page = _make_page(static_dir=static)
        result = page.asset("nonexistent.css")

        assert result == "/static/nonexistent.css"


class TestAssetProdWithManifest:
    def test_uses_fingerprinted_filename(self, tmp_path: Path) -> None:
        static = tmp_path / "static"
        static.mkdir()

        manifest = {"images/logo.png": "images/logo.a1b2c3d4e5f6.png"}
        page = _make_page(static_dir=static, asset_manifest=manifest)
        result = page.asset("images/logo.png")

        assert result == "/static/images/logo.a1b2c3d4e5f6.png"

    def test_falls_back_to_hash_for_unmanifested_files(self, tmp_path: Path) -> None:
        static = tmp_path / "static"
        static.mkdir()
        css = static / "extra.css"
        css.write_text("extra")

        manifest = {"images/logo.png": "images/logo.a1b2c3d4e5f6.png"}
        page = _make_page(static_dir=static, asset_manifest=manifest)
        result = page.asset("extra.css")

        expected_hash = hashlib.md5(css.read_bytes()).hexdigest()[:12]
        assert result == f"/static/extra.css?v={expected_hash}"


class TestAssetEdgeCases:
    def test_no_static_dir_returns_plain_url(self) -> None:
        page = _make_page(static_dir=None)
        result = page.asset("style.css")
        assert result == "/static/style.css"

    def test_custom_static_route(self, tmp_path: Path) -> None:
        static = tmp_path / "assets"
        static.mkdir()
        css = static / "style.css"
        css.write_text("body {}")

        page = _make_page(static_dir=static, static_url_path="/assets")
        result = page.asset("style.css")

        assert result.startswith("/assets/style.css?v=")

    def test_no_pywire_app_returns_fallback(self) -> None:
        page = BasePage.__new__(BasePage)
        page.request = MagicMock()
        page.request.app = MagicMock(spec=[])  # No state attribute

        result = page.asset("style.css")
        assert result == "/static/style.css"

    def test_subdirectory_path(self, tmp_path: Path) -> None:
        static = tmp_path / "static"
        (static / "css").mkdir(parents=True)
        css = static / "css" / "main.css"
        css.write_text("body {}")

        page = _make_page(static_dir=static)
        result = page.asset("css/main.css")

        expected_hash = hashlib.md5(css.read_bytes()).hexdigest()[:12]
        assert result == f"/static/css/main.css?v={expected_hash}"


class TestAssetWarnings:
    def test_missing_file_warns_in_dev(self, tmp_path: Path, caplog) -> None:
        static = tmp_path / "static"
        static.mkdir()

        page = _make_page(static_dir=static, is_dev_mode=True)

        with caplog.at_level(logging.WARNING, logger="pywire.runtime.page"):
            page.asset("missing.css")
            page.asset("missing.css")

        # Dev mode: warn every time (no dedup)
        warnings = [r for r in caplog.records if "missing.css" in r.message]
        assert len(warnings) == 2

    def test_missing_file_warns_once_in_prod(self, tmp_path: Path, caplog) -> None:
        static = tmp_path / "static"
        static.mkdir()

        warned: set = set()
        page = _make_page(
            static_dir=static, is_dev_mode=False, asset_warned_missing=warned
        )

        with caplog.at_level(logging.WARNING, logger="pywire.runtime.page"):
            page.asset("missing.css")
            page.asset("missing.css")

        # Prod mode: warn only once per path
        warnings = [r for r in caplog.records if "missing.css" in r.message]
        assert len(warnings) == 1

    def test_existing_file_no_warning(self, tmp_path: Path, caplog) -> None:
        static = tmp_path / "static"
        static.mkdir()
        (static / "exists.css").write_text("body {}")

        page = _make_page(static_dir=static)

        with caplog.at_level(logging.WARNING, logger="pywire.runtime.page"):
            page.asset("exists.css")

        warnings = [r for r in caplog.records if "exists.css" in r.message]
        assert len(warnings) == 0


class TestFingerprintStaticAssets:
    def test_creates_fingerprinted_and_original_copies(self, tmp_path: Path) -> None:
        static = tmp_path / "static"
        static.mkdir()
        (static / "logo.png").write_bytes(b"fake png data")
        (static / "style.css").write_text("body {}")

        out = tmp_path / "build"
        out.mkdir()

        manifest = fingerprint_static_assets(static, out)

        assert "logo.png" in manifest
        assert "style.css" in manifest

        # Both fingerprinted and original filenames must exist
        for original, fingerprinted in manifest.items():
            assert (out / "static" / fingerprinted).exists()
            assert (out / "static" / original).exists()

    def test_fingerprinted_filename_format(self, tmp_path: Path) -> None:
        static = tmp_path / "static"
        static.mkdir()
        content = b"test content"
        (static / "logo.png").write_bytes(content)

        out = tmp_path / "build"
        out.mkdir()

        manifest = fingerprint_static_assets(static, out)
        fingerprinted = manifest["logo.png"]

        expected_hash = hashlib.md5(content).hexdigest()[:12]
        assert fingerprinted == f"logo.{expected_hash}.png"

    def test_preserves_subdirectory_structure(self, tmp_path: Path) -> None:
        static = tmp_path / "static"
        (static / "images").mkdir(parents=True)
        (static / "images" / "icon.svg").write_text("<svg/>")

        out = tmp_path / "build"
        out.mkdir()

        manifest = fingerprint_static_assets(static, out)

        # Key should use forward slashes for path
        key = str(Path("images") / "icon.svg")
        assert key in manifest
        assert (out / "static" / manifest[key]).exists()

    def test_writes_manifest_json(self, tmp_path: Path) -> None:
        static = tmp_path / "static"
        static.mkdir()
        (static / "app.js").write_text("console.log('hi')")

        out = tmp_path / "build"
        out.mkdir()

        fingerprint_static_assets(static, out)

        manifest_path = out / "asset-manifest.json"
        assert manifest_path.exists()

        loaded = json.loads(manifest_path.read_text())
        assert "app.js" in loaded

    def test_cleans_previous_build_static(self, tmp_path: Path) -> None:
        static = tmp_path / "static"
        static.mkdir()
        (static / "new.css").write_text("new")

        out = tmp_path / "build"
        build_static = out / "static"
        build_static.mkdir(parents=True)
        (build_static / "old.abc123.css").write_text("stale")

        fingerprint_static_assets(static, out)

        # Old file should be gone
        assert not (build_static / "old.abc123.css").exists()
        # New file should be there
        assert any(f.name.startswith("new.") for f in build_static.iterdir())

    def test_content_change_produces_different_hash(self, tmp_path: Path) -> None:
        static = tmp_path / "static"
        static.mkdir()
        css = static / "style.css"

        out = tmp_path / "build"
        out.mkdir()

        css.write_text("v1")
        manifest1 = fingerprint_static_assets(static, out)

        css.write_text("v2")
        manifest2 = fingerprint_static_assets(static, out)

        assert manifest1["style.css"] != manifest2["style.css"]
