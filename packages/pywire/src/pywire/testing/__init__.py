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
# Importing pywire.testing without httpx/lxml is a developer error;
# this guard turns it into an ImportError instead of a confusing
# AttributeError on first use.
try:
    import httpx as _httpx  # noqa: F401
    import lxml.html as _lxml_html  # noqa: F401
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
