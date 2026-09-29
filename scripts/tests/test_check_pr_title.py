"""Tests for scripts/check_pr_title.py."""

import pytest

from check_pr_title import title_problems


@pytest.mark.parametrize(
    "title",
    [
        "fix(pywire-cli): handle missing config",
        "feat(pywire)!: model-bound forms with $bind",
        "fix(pywire,pywire-cli,pywire-language-server,create-pywire-app): bump pywire-parser and pywire-templates floors",
        "chore(main): release pywire-cli 0.4.0",
        "chore(pywire-docs): release 0.6.2",
        "chore: pin workflow actions by SHA",
        "feat!: drop Python 3.10",
    ],
)
def test_valid_titles(title):
    assert title_problems(title) == []


@pytest.mark.parametrize(
    "title, needle",
    [
        # #274's squash title: release-please failed to parse it and dropped it.
        ("Monorepo graph tool, CI hygiene, self-contained package checks", "not a conventional commit"),
        ("fix(pywire) handle x", "not a conventional commit"),
        ("fix(pywire):handle x", "not a conventional commit"),
        ("feature(pywire): add x", "unknown type"),
        ("fix(PyWire): add x", "bad scope"),
        ("fix(pywire): add x (again)", "parentheses"),
        ("fix(pywire):  ", "empty subject"),
        ("fix(pywire): trailing ", "whitespace"),
    ],
)
def test_invalid_titles(title, needle):
    problems = title_problems(title)
    assert any(needle in p for p in problems), problems
