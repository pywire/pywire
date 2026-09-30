"""Request checks shared by the auth routes: redirect targets and CSRF."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlsplit

from starlette.requests import Request


def safe_next(value: Optional[str], default: str) -> str:
    """``value`` if it is a path on this site, else ``default``.

    Only a path starting with one ``/`` is kept. ``//host``, ``/\\host``,
    ``https://host`` and anything with control characters could send the
    browser to another site (browsers treat ``\\`` like ``/`` and drop tabs
    and newlines), so a login link could not be used to phish.
    """
    if not value or not value.startswith("/") or value[1:2] in ("/", "\\"):
        return default
    if "\\" in value or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        return default
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return default
    return value


def is_cross_site(request: Request) -> bool:
    """True when the browser says this POST came from another site.

    ``Sec-Fetch-Site`` is set by the browser itself; ``Origin`` is the
    fallback for browsers without it. A request with neither did not come
    from a browser form, so CSRF does not apply.
    """
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        return site.lower() not in ("same-origin", "none")
    origin = request.headers.get("origin")
    if origin is None:
        return False
    if origin == "null":
        return True

    def hostname(netloc: str) -> str:
        return (urlsplit("//" + netloc.strip()).hostname or "").lower()

    hosts = {hostname(request.headers.get("host", ""))}
    forwarded = request.headers.get("x-forwarded-host")
    if forwarded:
        hosts.update(hostname(h) for h in forwarded.split(","))
    return (urlsplit(origin).hostname or "").lower() not in hosts
