"""Test helpers for PyWire apps.

Public API:

- :class:`TestClient` — composes ``starlette.testclient.TestClient`` with
  PyWire-aware methods (``submit_form``, ``fire_event``, ``force_login``).
- :func:`wire_page` — context manager that compiles an inline ``.wire``
  source string into a temporary PyWire app and returns a
  :class:`TestClient` over it.
- :func:`render_page` / :func:`render_component` — direct render helpers
  that bypass HTTP entirely; fastest path for pure-render assertions.
- :func:`make_principal` — convenience for constructing
  :class:`pywire.auth.ClaimsPrincipal` instances in tests.
- :class:`EventResult` — wrapper around the dict returned by
  :meth:`pywire.runtime.page.BasePage.render_update` exposing
  ``.regions``, ``.html``, ``.commands``, ``.meta`` as attributes.

This module requires the ``testing`` extra::

    pip install pywire[testing]

which pulls in ``httpx`` (for the TestClient transport) and ``lxml``
(for :meth:`TestClient.select`).
"""

from __future__ import annotations

# Fail loudly with an actionable message when the extra isn't installed.
# Importing pywire.testing without httpx/lxml/cssselect/starlette.testclient
# is a developer error; this guard turns it into an ImportError instead of
# a confusing AttributeError on first use. starlette.testclient itself
# requires httpx so we test it directly — that catches both vanilla
# starlette installs and partial extras setups.
try:
    import lxml.html  # noqa: F401
    from starlette.testclient import TestClient as _StarletteTestClient  # noqa: F401
except ImportError as exc:  # pragma: no cover - exercised only without extra
    raise ImportError(
        "pywire.testing requires the 'testing' extra. "
        "Install with: pip install 'pywire[testing]'"
    ) from exc

from pywire.testing.client import TestClient
from pywire.testing.events import EventResult
from pywire.testing.factories import make_principal, wire_page
from pywire.testing.render import render_component, render_page

__all__ = [
    "EventResult",
    "TestClient",
    "make_principal",
    "render_component",
    "render_page",
    "wire_page",
]
