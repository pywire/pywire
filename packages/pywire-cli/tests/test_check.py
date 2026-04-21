"""Tests for `pywire check` CLI command."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from pywire_cli.check import collect_diagnostics, format_plain, summarize
from pywire_cli.main import cli


def _write_pages(tmp_path: Path, src: str) -> Path:
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.wire").write_text(src)
    return pages


def test_collect_diagnostics_empty_dir(tmp_path: Path) -> None:
    pages = tmp_path / "pages"
    pages.mkdir()
    assert collect_diagnostics(pages) == []


def test_collect_diagnostics_detects_pw001(tmp_path: Path) -> None:
    pages = _write_pages(
        tmp_path,
        "---\nfrom datetime import datetime\nt = wire(datetime.now())\n---\n<p>{t}</p>\n",
    )
    diags = collect_diagnostics(pages)
    assert any(d.code == "PW001" for d in diags)


def test_summarize_exit_code_zero_when_clean() -> None:
    assert summarize([]).exit_code == 0


def test_summarize_exit_code_one_on_error(tmp_path: Path) -> None:
    pages = _write_pages(
        tmp_path,
        "---\ncount = wire(0)\n@derived\ndef bad():\n    count.value = 5\n---\n<p>{count}</p>\n",
    )
    diags = collect_diagnostics(pages)
    assert summarize(diags).exit_code == 1


def test_summarize_strict_mode_fails_on_warning(tmp_path: Path) -> None:
    pages = _write_pages(
        tmp_path,
        "---\nfrom datetime import datetime\nt = wire(datetime.now())\n---\n<p>{t}</p>\n",
    )
    diags = collect_diagnostics(pages)
    assert summarize(diags).exit_code == 0
    assert summarize(diags, strict=True).exit_code == 1


def test_format_plain_ruff_style(tmp_path: Path) -> None:
    pages = _write_pages(
        tmp_path,
        "---\ncount = wire(0)\n---\n<p>{count.value}</p>\n",
    )
    diags = collect_diagnostics(pages)
    out = format_plain(diags)
    assert "PW003" in out
    assert ":" in out  # file:line:col: ...


def test_cli_check_clean_project(tmp_path: Path) -> None:
    pages = _write_pages(tmp_path, "---\ncount = wire(0)\n---\n<p>{count}</p>\n")
    runner = CliRunner()
    result = runner.invoke(cli, ["check", "--pages-dir", str(pages)])
    assert result.exit_code == 0
    assert "No issues" in result.output


def test_cli_check_with_error_exits_1(tmp_path: Path) -> None:
    pages = _write_pages(
        tmp_path,
        "---\ncount = wire(0)\n@derived\ndef bad():\n    count.value = 1\n---\n<p>{count}</p>\n",
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["check", "--pages-dir", str(pages), "--plain"])
    assert result.exit_code == 1
    assert "PW002" in result.output


def test_cli_check_rule_filter(tmp_path: Path) -> None:
    pages = _write_pages(
        tmp_path,
        "---\nfrom datetime import datetime\n"
        "ts = wire(datetime.now())\n"
        "count = wire(0)\n"
        "---\n"
        "<p>{count.value}</p>\n",
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["check", "--pages-dir", str(pages), "--plain", "--rule", "PW003"],
    )
    # Should only report PW003, not PW001.
    assert "PW003" in result.output
    assert "PW001" not in result.output
