"""`pywire dev` port selection (#298)."""

import socket

import click
import pytest

from pywire_cli.main import _find_available_port


@pytest.fixture
def busy_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        yield s.getsockname()[1]


def test_default_port_falls_back_to_next_free_port(busy_port: int) -> None:
    assert _find_available_port("127.0.0.1", busy_port) > busy_port


def test_explicit_port_in_use_fails_loudly(busy_port: int) -> None:
    with pytest.raises(click.UsageError, match=f"Port {busy_port} is already in use"):
        _find_available_port("127.0.0.1", busy_port, max_attempts=1)


def test_explicit_free_port_is_used() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert _find_available_port("127.0.0.1", port, max_attempts=1) == port


def test_dev_passes_single_attempt_for_explicit_port(
    busy_port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from click.testing import CliRunner

    from pywire_cli import main as cli_main

    monkeypatch.setattr(cli_main, "import_app", lambda _app: None)
    result = CliRunner().invoke(
        cli_main.cli, ["dev", "main:app", "--port", str(busy_port), "--no-tui"]
    )
    assert result.exit_code == 2
    assert f"Port {busy_port} is already in use" in result.output
