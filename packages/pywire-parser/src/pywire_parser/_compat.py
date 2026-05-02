"""Runtime version-floor checks for upstream packages.

See packages/pywire/src/pywire/_compat.py for the rationale and
CLAUDE.md "Version Floors" for the bump protocol.
"""

from importlib.metadata import PackageNotFoundError, version

_FLOORS = {
    # tree-sitter-pywire ships the compiled grammar binary. New AST
    # node types in pywire-parser require matching grammar nodes.
    "tree-sitter-pywire": "0.6.0",
}


def _parse(v: str) -> tuple[int, ...]:
    out: list[int] = []
    for chunk in v.split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        out.append(int(digits) if digits else 0)
    return tuple(out)


for _pkg, _min in _FLOORS.items():
    try:
        _installed = version(_pkg)
    except PackageNotFoundError:
        continue
    if _parse(_installed) < _parse(_min):
        raise ImportError(
            f"pywire-parser requires {_pkg}>={_min} but found {_installed}. "
            f"Run: pip install -U pywire-parser  "
            f"(or upgrade {_pkg} directly: pip install -U '{_pkg}>={_min}')"
        )
