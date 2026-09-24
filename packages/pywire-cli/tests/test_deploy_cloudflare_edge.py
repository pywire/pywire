"""Tests for the cloudflare-edge target (stateless plain Worker, no DOs)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from pywire_cli.main import cli


def _make_app_dir() -> None:
    """Create a minimal PyWire app + empty build manifest for generate_cf_bundle."""
    Path("main.py").write_text(
        "from unittest.mock import MagicMock\n"
        "app = MagicMock()\n"
        "app.pages_dir = 'pages'\n"
        "app.static_dir = None\n"
    )
    Path("pages").mkdir(exist_ok=True)
    manifest = Path(".pywire") / "build" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"entries": {}}')


class TestBuildCloudflareEdge:
    @patch("pywire.compiler.build.build_project")
    def test_build_emits_stateless_worker_bundle(self, mock_build: MagicMock) -> None:
        mock_build.return_value = MagicMock(
            pages=0,
            layouts=0,
            components=0,
            static_assets=0,
            out_dir=".pywire/build",
        )
        runner = CliRunner()
        with runner.isolated_filesystem():
            _make_app_dir()
            result = runner.invoke(cli, ["build", "--platform", "cloudflare-edge"])
            assert result.exit_code == 0, result.output

            # entry.py drives one-shot requests through OneShotASGIAdapter
            entry = Path("entry.py").read_text()
            assert "OneShotASGIAdapter" in entry

            # wrangler.toml is a plain Worker: Python Workers, assets binding,
            # and NO Durable Objects
            wrangler = Path("wrangler.toml").read_text()
            assert "durable_objects" not in wrangler
            assert "python_workers" in wrangler

            # edge bundle carries no Durable Object class
            assert not Path("pywire_do.py").exists()


class TestDeployCloudflareEdge:
    @patch("pywire.compiler.build.build_project")
    def test_deploy_writes_stateless_configs(self, mock_build: MagicMock) -> None:
        mock_build.return_value = MagicMock(
            pages=0, layouts=0, components=0, out_dir=".pywire/build"
        )
        runner = CliRunner()
        with runner.isolated_filesystem():
            _make_app_dir()
            result = runner.invoke(cli, ["deploy", "--platform", "cloudflare-edge"])
            assert result.exit_code == 0, result.output

            assert "OneShotASGIAdapter" in Path("entry.py").read_text()
            assert "durable_objects" not in Path("wrangler.toml").read_text()
            assert not Path("pywire_do.py").exists()
