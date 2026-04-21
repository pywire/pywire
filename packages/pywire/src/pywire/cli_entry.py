"""Shim entry point for the `pywire` console script.

The CLI lives in the separate ``pywire-cli`` package, pulled in via the
``pywire[cli]`` extra. This shim forwards to it when installed, or prints a
short install hint otherwise, so a bare ``pip install pywire`` still wires up
the ``pywire`` command without forcing CLI dependencies on library users.
"""

from __future__ import annotations

import sys


def main() -> None:
    try:
        from pywire_cli.main import cli
    except ImportError:
        print(
            "Error: the `pywire` command requires the CLI extra.\n"
            "Install it with: uv add pywire[cli]  (or: pip install 'pywire[cli]')",
            file=sys.stderr,
        )
        sys.exit(1)
    cli()


if __name__ == "__main__":
    main()
