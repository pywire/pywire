"""Integration tests for the non-interactive oneliner mode.

Each test invokes ``main.main()`` with a real argv, lets the scaffolder
write into a pytest tmp_path, and inspects the generated file tree.
Subprocess calls (``git init``, ``uv sync``) are stubbed so tests are
fast and hermetic.

Questionary is NOT stubbed: any test that reaches a prompt is a failing
test — non-interactive mode is expected to bypass every questionary call.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Iterable

import pytest

from create_pywire_app import main as cpa_main


def _run(argv: list[str], *, cwd: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run main.main() with the given argv, as if the CLI was invoked."""
    monkeypatch.setattr(sys, "argv", ["create-pywire-app", *argv])
    monkeypatch.chdir(cwd)
    # Swallow subprocess side effects — git init, uv sync, etc.
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            args=a, returncode=0, stdout="", stderr=""
        ),
    )
    # Short-circuit the version resolver so we don't hit the network.
    monkeypatch.setattr(cpa_main, "resolve_pywire_version", lambda _dep: "0.0.0")

    cpa_main.main()


def _assert_has(path: Path, *relative: str) -> None:
    for rel in relative:
        assert (path / rel).exists(), f"expected {rel!r} under {path}"


def _assert_missing(path: Path, *relative: str) -> None:
    for rel in relative:
        assert not (path / rel).exists(), f"expected {rel!r} NOT to exist under {path}"


def _read_pyproject(path: Path) -> str:
    return (path / "pyproject.toml").read_text()


class TestBaselineYes:
    """-y with no other flags: defaults to counter + path + src + no adapters."""

    def test_generates_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "app"
        _run(
            [str(project), "-y", "--no-install", "--no-git"],
            cwd=tmp_path,
            monkeypatch=monkeypatch,
        )
        _assert_has(project, "pyproject.toml", "README.md", "src", ".gitignore")

    def test_default_template_is_counter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "app"
        _run(
            [str(project), "-y", "--no-install", "--no-git"],
            cwd=tmp_path,
            monkeypatch=monkeypatch,
        )
        # Counter template ships an index page + layout.
        pages = project / "src" / "pages"
        assert (pages / "index.wire").exists()

    def test_no_deploy_adapters_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "app"
        _run(
            [str(project), "-y", "--no-install", "--no-git"],
            cwd=tmp_path,
            monkeypatch=monkeypatch,
        )
        _assert_missing(
            project,
            "Dockerfile",
            "fly.toml",
            "render.yaml",
            "wrangler.toml",
            "railway.json",
        )


class TestTemplateVariations:
    @pytest.mark.parametrize("template", ["skeleton", "counter", "blog", "saas"])
    def test_each_template_scaffolds(
        self, template: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / f"app-{template}"
        _run(
            [str(project), "-y", "--template", template, "--no-install", "--no-git"],
            cwd=tmp_path,
            monkeypatch=monkeypatch,
        )
        _assert_has(project, "pyproject.toml", "src", "src/pages")

    def test_saas_gets_sqlalchemy_dep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "saas-app"
        _run(
            [str(project), "-y", "--template", "saas", "--no-install", "--no-git"],
            cwd=tmp_path,
            monkeypatch=monkeypatch,
        )
        content = _read_pyproject(project)
        assert "sqlalchemy" in content.lower()

    def test_blog_gets_markdown_dep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "blog-app"
        _run(
            [str(project), "-y", "--template", "blog", "--no-install", "--no-git"],
            cwd=tmp_path,
            monkeypatch=monkeypatch,
        )
        content = _read_pyproject(project)
        assert "markdown" in content.lower()


class TestDeployAdapters:
    @pytest.mark.parametrize(
        "adapter,expected_file",
        [
            ("docker", "Dockerfile"),
            ("render", "render.yaml"),
            ("fly", "fly.toml"),
            ("railway", "railway.json"),
            ("cloudflare", "wrangler.toml"),
        ],
    )
    def test_single_adapter_generates_config(
        self,
        adapter: str,
        expected_file: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project = tmp_path / f"app-{adapter}"
        _run(
            [
                str(project),
                "-y",
                "--template",
                "skeleton",
                "--deploy",
                adapter,
                "--no-install",
                "--no-git",
            ],
            cwd=tmp_path,
            monkeypatch=monkeypatch,
        )
        _assert_has(project, expected_file)

    def test_render_adapter_also_generates_dockerfile(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "render-app"
        _run(
            [
                str(project),
                "-y",
                "--template",
                "skeleton",
                "--deploy",
                "render",
                "--no-install",
                "--no-git",
            ],
            cwd=tmp_path,
            monkeypatch=monkeypatch,
        )
        _assert_has(project, "render.yaml", "Dockerfile")

    def test_cloudflare_generates_entry_and_do(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "cf-app"
        _run(
            [
                str(project),
                "-y",
                "--template",
                "skeleton",
                "--deploy",
                "cloudflare",
                "--no-install",
                "--no-git",
            ],
            cwd=tmp_path,
            monkeypatch=monkeypatch,
        )
        _assert_has(
            project, "wrangler.toml", "entry.py", "pywire_do.py", ".wranglerignore"
        )

    def test_multiple_adapters(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "multi-app"
        _run(
            [
                str(project),
                "-y",
                "--template",
                "skeleton",
                "--deploy",
                "docker",
                "--deploy",
                "fly",
                "--deploy",
                "render",
                "--no-install",
                "--no-git",
            ],
            cwd=tmp_path,
            monkeypatch=monkeypatch,
        )
        _assert_has(project, "Dockerfile", "fly.toml", "render.yaml")


class TestLayoutAndRouting:
    def test_no_src_flat_layout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "flat-app"
        _run(
            [
                str(project),
                "-y",
                "--template",
                "skeleton",
                "--no-src",
                "--no-install",
                "--no-git",
            ],
            cwd=tmp_path,
            monkeypatch=monkeypatch,
        )
        # Flat layout: pages/ lives at project root, no src/.
        _assert_has(project, "pages")
        _assert_missing(project, "src")

    def test_explicit_routing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "explicit-app"
        _run(
            [
                str(project),
                "-y",
                "--template",
                "counter",
                "--routing",
                "explicit",
                "--no-install",
                "--no-git",
            ],
            cwd=tmp_path,
            monkeypatch=monkeypatch,
        )
        _assert_has(project, "src/main.py")


class TestRedisScaling:
    def test_redis_with_docker_adapter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "redis-app"
        _run(
            [
                str(project),
                "-y",
                "--template",
                "skeleton",
                "--deploy",
                "docker",
                "--redis",
                "--workers",
                "4",
                "--no-install",
                "--no-git",
            ],
            cwd=tmp_path,
            monkeypatch=monkeypatch,
        )
        dockerfile = (project / "Dockerfile").read_text()
        # Dockerfile template substitutes workers — verify the render picked up the flag.
        assert "4" in dockerfile


class TestGuards:
    def test_refuse_scaffold_into_non_empty_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "existing"
        project.mkdir()
        (project / "stuff.txt").write_text("do not clobber")

        with pytest.raises(SystemExit) as excinfo:
            _run(
                [str(project), "-y", "--no-install", "--no-git"],
                cwd=tmp_path,
                monkeypatch=monkeypatch,
            )
        assert excinfo.value.code == 1
        # Original file must survive.
        assert (project / "stuff.txt").read_text() == "do not clobber"

    def test_empty_existing_dir_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "empty"
        project.mkdir()
        _run(
            [str(project), "-y", "--no-install", "--no-git"],
            cwd=tmp_path,
            monkeypatch=monkeypatch,
        )
        _assert_has(project, "pyproject.toml")


class TestSubprocessGating:
    """--no-git / --no-install should prevent subprocess.run from being called
    with git / uv invocations. Any call that slips through is a bug."""

    def _collect_calls(self, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
        calls: list[list[str]] = []

        def recorder(*args, **kwargs):
            # subprocess.run(cmd, ...) or subprocess.run(cmd, check=True, ...)
            cmd = args[0] if args else kwargs.get("args")
            if isinstance(cmd, (list, tuple)):
                calls.append(list(cmd))
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )

        monkeypatch.setattr(subprocess, "run", recorder)
        monkeypatch.setattr(cpa_main, "resolve_pywire_version", lambda _dep: "0.0.0")
        return calls

    def _run_capturing(
        self, argv: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> list[list[str]]:
        calls = self._collect_calls(monkeypatch)
        monkeypatch.setattr(sys, "argv", ["create-pywire-app", *argv])
        monkeypatch.chdir(tmp_path)
        cpa_main.main()
        return calls

    @staticmethod
    def _matches(calls: Iterable[list[str]], exe: str) -> bool:
        return any(cmd and exe in cmd[0] for cmd in calls)

    def test_no_git_skips_git_init(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._run_capturing(
            [str(tmp_path / "app"), "-y", "--no-install", "--no-git"],
            tmp_path,
            monkeypatch,
        )
        assert not self._matches(calls, "git")

    def test_no_install_skips_uv_sync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._run_capturing(
            [str(tmp_path / "app"), "-y", "--no-install", "--no-git"],
            tmp_path,
            monkeypatch,
        )
        assert not any(cmd[:2] == ["uv", "sync"] for cmd in calls)


class TestNonInteractiveTrigger:
    """Only --yes triggers full non-interactive. A bare PROJECT_PATH without --yes
    still falls through to questionary for anything unprovided — we verify by
    asserting the empty-dir guard is NOT applied in that case."""

    def test_project_path_alone_is_not_non_interactive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # If this invocation were non-interactive, the pre-existing file would
        # trigger the overwrite guard and raise SystemExit(1). Without --yes,
        # the guard is skipped and we'd instead block on a questionary prompt.
        # We stub questionary to raise so the test doesn't hang.
        project = tmp_path / "pre-existing"
        project.mkdir()
        (project / "marker.txt").write_text("x")

        import questionary

        def _raise(*_a, **_kw):
            raise RuntimeError("questionary was reached — interactive path active")

        # Patch every factory we might hit; any of them tripping means the path is interactive.
        for name in ("path", "select", "confirm", "checkbox", "text"):
            monkeypatch.setattr(questionary, name, _raise)
        monkeypatch.setattr(cpa_main, "resolve_pywire_version", lambda _dep: "0.0.0")
        monkeypatch.setattr(sys, "argv", ["create-pywire-app", str(project)])
        monkeypatch.chdir(tmp_path)

        with pytest.raises(RuntimeError, match="questionary was reached"):
            cpa_main.main()

        # Marker file must be untouched — guard was NOT applied (that's the point),
        # but we also didn't clobber before reaching the prompt.
        assert (project / "marker.txt").read_text() == "x"
