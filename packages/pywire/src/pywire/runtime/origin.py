"""Where a request came from: cross-site checks and loopback-only dev routes.

Shared by every transport. A browser marks the requests it sends for a page
(form POSTs, WebSocket handshakes, fetches); a page on another site must not
open a live connection that acts with the user's cookies, and dev-only
endpoints must not answer a hostname an attacker's DNS points at localhost.
"""

from __future__ import annotations

from typing import Mapping
from urllib.parse import urlsplit

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _hostname(netloc: str) -> str:
    # Ports are left out: cookies are shared across ports anyway, and
    # proxies often drop the port from Host.
    return (urlsplit("//" + netloc.strip()).hostname or "").lower()


def is_cross_site(headers: Mapping[str, str]) -> bool:
    """True when a browser says this request came from another site.

    ``Sec-Fetch-Site`` is set by the browser itself (also on WebSocket
    handshakes); ``Origin`` is the fallback for browsers without it. A
    request with neither did not come from a browser page (a CLI or server
    client), so there is no victim's cookie jar to protect.
    """
    site = headers.get("sec-fetch-site")
    if site is not None:
        return site.lower() not in ("same-origin", "none")
    origin = headers.get("origin")
    if origin is None:
        return False
    if origin == "null":
        return True
    hosts = {_hostname(headers.get("host", ""))}
    forwarded = headers.get("x-forwarded-host")
    if forwarded:
        hosts.update(_hostname(h) for h in forwarded.split(","))
    return (urlsplit(origin).hostname or "").lower() not in hosts


def is_loopback_host(headers: Mapping[str, str]) -> bool:
    """True when the ``Host`` header names this machine by a loopback name.

    Dev-only endpoints check this so a DNS-rebinding page (``evil.example``
    re-pointed at 127.0.0.1) cannot reach them: its requests carry its own
    hostname.
    """
    return _hostname(headers.get("host", "")) in _LOOPBACK_HOSTS
