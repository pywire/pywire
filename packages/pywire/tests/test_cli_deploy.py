"""Tests for the pywire deploy CLI command."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from pywire.cli.deploy import (
    generate_dockerfile,
    generate_render_yaml,
    validate_deploy_config,
)
from pywire.cli.main import cli


class TestGenerateDockerfile:
    def test_returns_valid_dockerfile(self) -> None:
        content = generate_dockerfile(Path("."))
        assert "FROM python:3.12-slim" in content
        assert "COPY pyproject.toml uv.lock ./" in content
        assert "EXPOSE 8000" in content
        assert "pywire" in content


class TestGenerateRenderYaml:
    def test_includes_project_name(self) -> None:
        content = generate_render_yaml(Path("."), "my-app")
        assert "name: my-app" in content
        assert "runtime: python" in content
        assert "pywire run" in content

    def test_substitutes_different_names(self) -> None:
        content = generate_render_yaml(Path("."), "cool-project")
        assert "name: cool-project" in content


class TestValidateDeployConfig:
    def test_missing_pyproject(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            issues = validate_deploy_config("docker", Path(tmpdir))
            assert any("pyproject.toml" in i for i in issues)

    def test_missing_uv_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create pyproject.toml but no uv.lock
            (Path(tmpdir) / "pyproject.toml").write_text("[project]\nname='test'\n")
            issues = validate_deploy_config("docker", Path(tmpdir))
            assert any("uv.lock" in i for i in issues)

    def test_all_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "pyproject.toml").write_text("[project]\nname='test'\n")
            (Path(tmpdir) / "uv.lock").write_text("")
            issues = validate_deploy_config("docker", Path(tmpdir))
            assert issues == []

    def test_render_missing_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "pyproject.toml").write_text("[project]\nname='test'\n")
            issues = validate_deploy_config("render", Path(tmpdir))
            assert any("uv.lock" in i for i in issues)


def _make_app_dir(tmpdir: str) -> None:
    """Create a minimal PyWire app in tmpdir for auto-discovery."""
    main_py = Path(tmpdir) / "main.py"
    main_py.write_text(
        "from unittest.mock import MagicMock\n"
        "app = MagicMock()\n"
        "app.pages_dir = 'pages'\n"
    )
    (Path(tmpdir) / "pyproject.toml").write_text("[project]\nname='test'\n")
    (Path(tmpdir) / "uv.lock").write_text("")
    (Path(tmpdir) / "pages").mkdir(exist_ok=True)


class TestDeployCommand:
    @patch("pywire.compiler.build.build_project")
    def test_docker_generates_dockerfile(self, mock_build: MagicMock) -> None:
        mock_build.return_value = MagicMock(
            pages=0, layouts=0, components=0, out_dir=".pywire/build"
        )
        runner = CliRunner()
        with runner.isolated_filesystem() as tmpdir:
            _make_app_dir(tmpdir)
            result = runner.invoke(cli, ["deploy", "--platform", "docker"])
            assert result.exit_code == 0, result.output
            assert Path("Dockerfile").exists()
            content = Path("Dockerfile").read_text()
            assert "FROM python:3.12-slim" in content

    @patch("pywire.compiler.build.build_project")
    def test_render_generates_yaml(self, mock_build: MagicMock) -> None:
        mock_build.return_value = MagicMock(
            pages=0, layouts=0, components=0, out_dir=".pywire/build"
        )
        runner = CliRunner()
        with runner.isolated_filesystem() as tmpdir:
            _make_app_dir(tmpdir)
            result = runner.invoke(cli, ["deploy", "--platform", "render"])
            assert result.exit_code == 0, result.output
            assert Path("render.yaml").exists()
            content = Path("render.yaml").read_text()
            assert "runtime: python" in content

    @patch("pywire.compiler.build.build_project")
    def test_fly_prints_stub_warning(self, mock_build: MagicMock) -> None:
        mock_build.return_value = MagicMock(
            pages=0, layouts=0, components=0, out_dir=".pywire/build"
        )
        runner = CliRunner()
        with runner.isolated_filesystem() as tmpdir:
            _make_app_dir(tmpdir)
            result = runner.invoke(cli, ["deploy", "--platform", "fly"])
            assert result.exit_code == 0, result.output
            assert "coming soon" in result.output

    @patch("pywire.compiler.build.build_project")
    def test_existing_file_asks_overwrite(self, mock_build: MagicMock) -> None:
        mock_build.return_value = MagicMock(
            pages=0, layouts=0, components=0, out_dir=".pywire/build"
        )
        runner = CliRunner()
        with runner.isolated_filesystem() as tmpdir:
            _make_app_dir(tmpdir)
            Path("Dockerfile").write_text("old content")
            # Decline overwrite
            result = runner.invoke(cli, ["deploy", "--platform", "docker"], input="n\n")
            assert result.exit_code == 0, result.output
            assert "Aborted" in result.output
            assert Path("Dockerfile").read_text() == "old content"

    @patch("pywire.compiler.build.build_project")
    def test_existing_file_overwrite_confirmed(self, mock_build: MagicMock) -> None:
        mock_build.return_value = MagicMock(
            pages=0, layouts=0, components=0, out_dir=".pywire/build"
        )
        runner = CliRunner()
        with runner.isolated_filesystem() as tmpdir:
            _make_app_dir(tmpdir)
            Path("Dockerfile").write_text("old content")
            # Confirm overwrite
            result = runner.invoke(cli, ["deploy", "--platform", "docker"], input="y\n")
            assert result.exit_code == 0, result.output
            assert "FROM python:3.12-slim" in Path("Dockerfile").read_text()

    def test_validation_catches_missing_pyproject(self) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem():
            # Create app file but no pyproject.toml
            Path("main.py").write_text(
                "from unittest.mock import MagicMock\n"
                "app = MagicMock()\n"
                "app.pages_dir = 'pages'\n"
            )
            Path("pages").mkdir()
            with patch("pywire.compiler.build.build_project") as mock_build:
                mock_build.return_value = MagicMock(
                    pages=0, layouts=0, components=0, out_dir=".pywire/build"
                )
                result = runner.invoke(cli, ["deploy", "--platform", "docker"])
                assert result.exit_code == 0, result.output
                assert "pyproject.toml" in result.output
