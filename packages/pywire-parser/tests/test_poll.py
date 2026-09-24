"""Tests for the ``@poll`` directive's parse-time validation.

``@poll`` reuses the generic ``EventAttribute`` AST (``event_type="poll"``);
the parser only adds validation the generic event path lacks: poll modifiers
must be ``every-<int>`` with ``<int> >= 100`` (a FaaS billing foot-gun below
that). Unknown modifiers are compile-time errors.
"""

from __future__ import annotations

import pytest

from pywire_parser.ast_nodes import EventAttribute
from pywire_parser.exceptions import PyWireSyntaxError
from pywire_parser.parser import PyWireParser


def _poll(src: str) -> EventAttribute:
    parsed = PyWireParser().parse(src)
    node = parsed.template[0]
    attr = node.special_attributes[0]
    assert isinstance(attr, EventAttribute)
    return attr


def test_poll_parses_to_event_attribute_with_modifier() -> None:
    attr = _poll("<button @poll.every-400={tick()}>t</button>")
    assert attr.event_type == "poll"
    assert attr.handler_name == "tick()"
    assert attr.modifiers == ["every-400"]


def test_poll_default_has_no_modifiers() -> None:
    attr = _poll("<button @poll={tick()}>t</button>")
    assert attr.event_type == "poll"
    assert attr.modifiers == []


def test_poll_every_below_100_rejected() -> None:
    with pytest.raises(PyWireSyntaxError):
        PyWireParser().parse("<button @poll.every-50={tick()}>t</button>")


def test_poll_unknown_modifier_rejected() -> None:
    with pytest.raises(PyWireSyntaxError):
        PyWireParser().parse("<button @poll.bogus={tick()}>t</button>")


def test_poll_non_integer_interval_rejected() -> None:
    with pytest.raises(PyWireSyntaxError):
        PyWireParser().parse("<button @poll.every-fast={tick()}>t</button>")
