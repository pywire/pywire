"""Runtime version-floor checks for upstream packages.

See packages/pywire/src/pywire/_compat.py for the rationale and
CLAUDE.md "Version Floors" for the bump protocol.
"""

from importlib.metadata import PackageNotFoundError, version

_FLOORS = {
    # pywire-secure stashes the CSRF token on scope and relies on
    # BasePage.csrf_token, added in the same monorepo release wave as
    # pywire-secure 0.1.0. Bump in lockstep when release-please cuts
    # the next pywire after the BasePage.csrf_token attribute lands.
    "pywire": "0.14.3",
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
            f"pywire-secure requires {_pkg}>={_min} but found {_installed}. "
            f"Run: pip install -U '{_pkg}>={_min}'"
        )
