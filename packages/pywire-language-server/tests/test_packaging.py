"""Packaging regressions."""

import re
from importlib.metadata import requires

from pywire_language_server._compat import _FLOORS


def _declared() -> set[str]:
    return {
        re.split(r"[<>=!~;\[ ]", req, maxsplit=1)[0].lower()
        for req in requires("pywire-language-server") or []
        if "extra ==" not in req
    }


def test_server_imports_are_declared_dependencies() -> None:
    # Regression for #286: server.py imports `pywire`, but 0.7.2 didn't
    # declare it, so `uv tool install pywire-language-server` crashed.
    assert {"pywire", "pywire-parser"} <= _declared()


def test_runtime_floors_cover_workspace_dependencies() -> None:
    assert set(_FLOORS) == {"pywire", "pywire-parser"}
