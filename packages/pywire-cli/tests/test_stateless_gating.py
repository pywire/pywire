"""Fail-fast stateless config checks for `pywire build` on pure-FaaS platforms.

Pure-FaaS targets (cloudflare-edge, aws-lambda, azure-functions, gcp-functions)
only work with `PyWire(stateless=True)` + a signing secret. gcp-cloudrun and
cloudflare (Durable Objects) accept either mode.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from pywire_cli.main import cli

FAAS_PLATFORMS = ["cloudflare-edge", "aws-lambda", "azure-functions", "gcp-functions"]

INDEX_WIRE = "---\ncount = wire(0)\n---\n<p>{count}</p>\n"


def _norm(text: str) -> str:
    """Collapse rich's line wrapping so substring asserts are stable."""
    return " ".join(text.split())


def _build_summary() -> MagicMock:
    return MagicMock(
        pages=1, layouts=0, components=0, static_assets=0, out_dir=".pywire/build"
    )


def _write_app(*, stateless: bool) -> None:
    """Minimal real PyWire app fixture in the CWD (module name: main)."""
    Path("pages").mkdir(exist_ok=True)
    (Path("pages") / "index.wire").write_text(INDEX_WIRE)
    source = "from pywire import PyWire\n"
    if stateless:
        # Secret comes from PYWIRE_SECRET_KEY (set/delenv'd per test) — the
        # PyWire constructor raises RuntimeError when it is missing.
        source += "app = PyWire(pages_dir='pages', stateless=True)\n"
    else:
        source += "app = PyWire(pages_dir='pages')\n"
    Path("main.py").write_text(source)
    manifest = Path(".pywire") / "build" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"entries": {}}')


@pytest.fixture(autouse=True)
def _isolate_app_module():
    """Each fixture app is a fresh `main` module; reset the compiler tier."""
    sys.modules.pop("main", None)
    yield
    sys.modules.pop("main", None)
    from pywire.compiler.tier_gate import set_stateless_tier

    set_stateless_tier(False)


@pytest.mark.parametrize("platform", FAAS_PLATFORMS)
def test_build_faas_rejects_stateful_app(
    platform: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYWIRE_SECRET_KEY", "test-secret")
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_app(stateless=False)
        with (
            patch("pywire.compiler.build.build_project") as mock_build,
            patch("pywire_cli.main._install_aws_dependencies"),
        ):
            mock_build.return_value = _build_summary()
            result = runner.invoke(cli, ["build", "--platform", platform])
    assert result.exit_code != 0
    assert "stateless=True" in _norm(result.output)


def test_build_aws_lambda_accepts_stateless_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYWIRE_SECRET_KEY", "test-secret")
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_app(stateless=True)
        with (
            patch("pywire.compiler.build.build_project") as mock_build,
            patch("pywire_cli.main._install_aws_dependencies") as mock_install,
        ):
            mock_build.return_value = _build_summary()
            result = runner.invoke(cli, ["build", "--platform", "aws-lambda"])
        assert result.exit_code == 0, result.output
        assert (Path(".pywire") / "deploy" / "aws" / "handler.py").exists()
        mock_install.assert_called_once()


def test_build_faas_missing_secret_names_provider_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYWIRE_SECRET_KEY", raising=False)
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_app(stateless=True)
        with patch("pywire.compiler.build.build_project") as mock_build:
            mock_build.return_value = _build_summary()
            result = runner.invoke(cli, ["build", "--platform", "aws-lambda"])
    assert result.exit_code != 0
    assert "set PYWIRE_SECRET_KEY in your provider environment" in _norm(result.output)


@pytest.mark.parametrize("platform", ["gcp-cloudrun", "cloudflare"])
def test_build_dual_mode_platforms_accept_stateful_app(platform: str) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_app(stateless=False)
        with patch("pywire.compiler.build.build_project") as mock_build:
            mock_build.return_value = _build_summary()
            result = runner.invoke(cli, ["build", "--platform", platform])
    assert result.exit_code == 0, result.output


def test_deploy_faas_rejects_stateful_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """`pywire deploy` must hit the same pure-FaaS stateless gate as `build`."""
    monkeypatch.setenv("PYWIRE_SECRET_KEY", "test-secret")
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_app(stateless=False)
        with (
            patch("pywire.compiler.build.build_project") as mock_build,
            patch("pywire_cli.main._install_aws_dependencies"),
        ):
            mock_build.return_value = _build_summary()
            result = runner.invoke(cli, ["deploy", "--platform", "aws-lambda"])
    assert result.exit_code != 0
    assert "stateless=True" in _norm(result.output)
