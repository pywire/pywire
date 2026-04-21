"""Tests for the pywire_parser.analysis rule engine."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from pywire_parser.analysis import Severity, analyze
from pywire_parser.parser import PyWireParser


def _analyze(src: str):
    with tempfile.NamedTemporaryFile("w", suffix=".wire", delete=False) as f:
        f.write(src)
        path = f.name
    parsed = PyWireParser().parse_file(Path(path))
    return analyze(parsed, path)


class TestPW001NonSerializableWire:
    def test_serializable_literals_ok(self) -> None:
        diags = _analyze(
            "---\n"
            "count = wire(0)\n"
            "name = wire('hello')\n"
            "items = wire([1, 2, 3])\n"
            "data = wire({'a': 1})\n"
            "none_val = wire(None)\n"
            "---\n"
            "<p>{count}</p>\n"
        )
        assert [d for d in diags if d.code == "PW001"] == []

    def test_datetime_flagged(self) -> None:
        diags = _analyze(
            "---\n"
            "from datetime import datetime\n"
            "ts = wire(datetime.now())\n"
            "---\n"
            "<p>{ts}</p>\n"
        )
        pw001 = [d for d in diags if d.code == "PW001"]
        assert len(pw001) == 1
        assert "datetime" in pw001[0].message
        assert pw001[0].severity == Severity.WARNING

    def test_suffix_heuristic_flagged(self) -> None:
        diags = _analyze("---\ndb = wire(DatabaseConnection())\n---\n<p>{db}</p>\n")
        pw001 = [d for d in diags if d.code == "PW001"]
        assert len(pw001) == 1
        assert "Connection" in pw001[0].message

    def test_lambda_flagged(self) -> None:
        diags = _analyze("---\nfn = wire(lambda: 1)\n---\n<p>{fn}</p>\n")
        pw001 = [d for d in diags if d.code == "PW001"]
        assert len(pw001) == 1
        assert "callable" in pw001[0].message.lower()


class TestPW002WriteInsideDerived:
    def test_assignment_to_value_flagged(self) -> None:
        diags = _analyze(
            "---\n"
            "count = wire(0)\n"
            "@derived\n"
            "def bad():\n"
            "    count.value = 5\n"
            "---\n"
            "<p>{count}</p>\n"
        )
        pw002 = [d for d in diags if d.code == "PW002"]
        assert len(pw002) == 1
        assert pw002[0].severity == Severity.ERROR

    def test_aug_assign_flagged(self) -> None:
        diags = _analyze(
            "---\n"
            "count = wire(0)\n"
            "@derived\n"
            "def bad():\n"
            "    count += 1\n"
            "---\n"
            "<p>{count}</p>\n"
        )
        assert any(d.code == "PW002" for d in diags)

    def test_read_only_derived_ok(self) -> None:
        diags = _analyze(
            "---\n"
            "count = wire(0)\n"
            "@derived\n"
            "def doubled():\n"
            "    return count.value * 2\n"
            "---\n"
            "<p>{doubled}</p>\n"
        )
        assert [d for d in diags if d.code == "PW002"] == []

    def test_nested_function_body_not_flagged(self) -> None:
        # Writing to a wire inside a helper function DEFINED in a derived
        # body is fine — the helper is not itself the derived computation.
        diags = _analyze(
            "---\n"
            "count = wire(0)\n"
            "@derived\n"
            "def safe():\n"
            "    def _callback():\n"
            "        count.value = 1\n"
            "    return count.value + 1\n"
            "---\n"
            "<p>{safe}</p>\n"
        )
        assert [d for d in diags if d.code == "PW002"] == []


class TestPW003RedundantValueInInterpolation:
    def test_wire_dot_value_flagged(self) -> None:
        diags = _analyze("---\ncount = wire(0)\n---\n<p>{count.value}</p>\n")
        pw003 = [d for d in diags if d.code == "PW003"]
        assert len(pw003) == 1
        assert pw003[0].severity == Severity.INFO

    def test_bare_wire_ok(self) -> None:
        diags = _analyze("---\ncount = wire(0)\n---\n<p>{count}</p>\n")
        assert [d for d in diags if d.code == "PW003"] == []

    def test_non_wire_attribute_ok(self) -> None:
        diags = _analyze("---\nuser = {'name': 'alice'}\n---\n<p>{user.name}</p>\n")
        assert [d for d in diags if d.code == "PW003"] == []


class TestRegistryAndEngine:
    def test_all_stubs_registered(self) -> None:
        from pywire_parser.analysis import all_rule_codes

        codes = set(all_rule_codes())
        assert {"PW001", "PW002", "PW003"} <= codes
        assert {"PW004", "PW005", "PW006", "PW007", "PW008", "PW009", "PW010"} <= codes

    def test_stub_raises_notimplemented_is_skipped(self) -> None:
        # Engine swallows NotImplementedError so stubs don't break output.
        diags = _analyze("---\ncount = wire(0)\n---\n<p>{count}</p>\n")
        assert isinstance(diags, list)  # no exception raised


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
