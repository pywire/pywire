"""Tests for the ``!live`` page directive."""

from __future__ import annotations

import pytest

from pywire_parser.ast_nodes import LiveDirective
from pywire_parser.exceptions import PyWireSyntaxError
from pywire_parser.parser import PyWireParser


def _live(directive: str) -> LiveDirective:
    parsed = PyWireParser().parse(f"{directive}\n<p>x</p>")
    found = parsed.get_directive_by_type(LiveDirective)
    assert isinstance(found, LiveDirective)
    return found


@pytest.mark.parametrize(
    ("directive", "every_ms"),
    [
        ("!live 2s", 2000),
        ("!live 1.5s", 1500),
        ("!live 500ms", 500),
        ("!live 100ms", 100),
        ("!live off", 0),
    ],
)
def test_live_intervals(directive: str, every_ms: int) -> None:
    assert _live(directive).every_ms == every_ms


@pytest.mark.parametrize("directive", ["!live", "!live 2", "!live soon", "!live 2m"])
def test_live_needs_an_interval_with_a_unit(directive: str) -> None:
    with pytest.raises(PyWireSyntaxError, match="!live takes an interval"):
        _live(directive)


def test_live_below_100ms_rejected() -> None:
    with pytest.raises(PyWireSyntaxError, match="at least 100ms"):
        _live("!live 50ms")
