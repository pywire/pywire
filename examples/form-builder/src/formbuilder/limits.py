"""Per-visitor rate limits, so the API keys behind the demo can't be drained.

Each build, refine or sample fill costs one unit from two buckets: one for
the visitor's cookie and one for their IP. Clearing cookies doesn't reset
the IP bucket, and people behind one office IP each still get their own
cookie bucket until the (larger) IP bucket runs out.

``MemoryLimiter`` keeps counts in the process. That's right for one server;
on Cloudflare every isolate has its own memory, so a deploy there swaps in a
limiter backed by a Durable Object or KV behind the same ``Limiter`` shape.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from collections import deque
from typing import Any, Deque, Dict, Optional, Protocol, Tuple

COOKIE = "fb_visitor"


class Limiter(Protocol):
    def take(self, key: str, limit: int, window: int) -> Optional[float]:
        """Spend one unit; ``None`` if allowed, else seconds until one frees up."""
        ...


class MemoryLimiter:
    """Sliding window, in process memory."""

    def __init__(self, max_keys: int = 50_000) -> None:
        self._hits: Dict[str, Deque[float]] = {}
        self._max_keys = max_keys

    def take(self, key: str, limit: int, window: int) -> Optional[float]:
        now = time.monotonic()
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= self._max_keys:
                self._prune(now, window)
            hits = self._hits[key] = deque()
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= limit:
            return hits[0] + window - now
        hits.append(now)
        return None

    def _prune(self, now: float, window: int) -> None:
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= now - window]:
            del self._hits[key]

    def clear(self) -> None:
        self._hits.clear()


def new_visitor_id() -> str:
    return secrets.token_urlsafe(16)


def _hash(text: str) -> str:
    # Keys hold hashes, not raw IPs or cookie values.
    return hashlib.sha256(text.encode()).hexdigest()[:24]


def visitor_keys(request: Any, ip_header: str) -> Tuple[str, str]:
    """(cookie key, IP key) for a request or WebSocket handshake."""
    cookies = getattr(request, "cookies", None) or {}
    visitor = cookies.get(COOKIE, "") if hasattr(cookies, "get") else ""
    ip = ""
    headers = getattr(request, "headers", None)
    if ip_header and headers is not None:
        ip = (headers.get(ip_header) or "").split(",")[0].strip()
    if not ip:
        client = getattr(request, "client", None)
        ip = getattr(client, "host", "") or ""
    # No cookie (blocked, or a script): everyone without one shares a bucket
    # per IP, which is stricter, not looser.
    return "v:" + _hash(visitor or "none:" + ip), "ip:" + _hash(ip or "unknown")


class VisitorCookie:
    """ASGI middleware: give each browser a random visitor id cookie."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("method") != "GET":
            await self.app(scope, receive, send)
            return
        cookie_header = b"; ".join(v for k, v in scope["headers"] if k == b"cookie")
        if (COOKIE + "=").encode() in cookie_header:
            await self.app(scope, receive, send)
            return
        value = new_visitor_id()
        # Later handlers in this same request (the first page render) see it.
        scope = dict(scope)
        scope["headers"] = [
            *[(k, v) for k, v in scope["headers"] if k != b"cookie"],
            (
                b"cookie",
                b"; ".join(filter(None, [cookie_header, f"{COOKIE}={value}".encode()])),
            ),
        ]
        # It only names a rate-limit bucket, so it isn't a secret or a login.
        flags = "; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax"

        async def send_with_cookie(message: Any) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"set-cookie", f"{COOKIE}={value}{flags}".encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cookie)
