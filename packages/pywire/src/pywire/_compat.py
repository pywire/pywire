"""Runtime version-floor checks for upstream PyWire packages.

When an upstream package adds features this package depends on, bump
the floor here AND in pyproject.toml. The pyproject floor lets pip's
resolver block bad combos at install time; this runtime check catches
stale envs that bypass the resolver (cached venvs, --no-deps, broken
lockfiles, monorepo editable installs that drift from pinned versions).

Floors are skipped silently when the upstream package is not installed
(extras-only deps). Lazy import sites that genuinely need the package
are responsible for their own missing-dep error message.

See CLAUDE.md "Version Floors" for the bump protocol.
"""

from importlib.metadata import PackageNotFoundError, version

_FLOORS = {
    # pywire-parser is a [build] extra. When installed, must match the
    # AST/directive surface this pywire release was built against.
    "pywire-parser": "0.6.0",
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
            f"pywire requires {_pkg}>={_min} but found {_installed}. "
            f"Run: pip install -U '{_pkg}>={_min}'"
        )
