"""The form builder app.

Stateless by default (``STATELESS=0`` for the WebSocket tier): each click and
each progress tick is one self-contained POST, so it runs on a plain
request/response host such as Cloudflare Python Workers.
"""

from __future__ import annotations

from formbuilder.limits import VisitorCookie
from formbuilder.settings import settings

from pywire import PyWire


def create_app(*, stateless: bool) -> PyWire:
    # Stateless mode signs the client-held page state with PYWIRE_SECRET_KEY
    # (at least 32 bytes); it comes from the environment.
    return PyWire(
        pages_dir="src/pages", stateless=stateless, middleware=[VisitorCookie]
    )


app = create_app(stateless=settings.stateless)
