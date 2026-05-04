"""Stateless HMAC CSRF tokens.

A token is ``"{ts}:{sig}"`` where ``sig = HMAC-SHA256(DOMAIN + ":" +
session_id + ":" + ts, secret)`` truncated to 32 hex chars. The HMAC is
domain-separated by :data:`DOMAIN` so a session-cookie signing key cannot
be confused with a CSRF token under the same secret.

Tokens carry a Unix-second timestamp; verification rejects tokens older
than ``ttl`` seconds. Setting ``ttl=0`` disables expiry entirely (useful
for tests; production apps should keep the default).

The session id is part of the signed payload so a token issued for one
session cannot be replayed against another.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Optional

DOMAIN = "pywire-csrf-v1"
_SIG_LEN = 32
_DEFAULT_TTL = 3600


def generate_token(
    session_id: str,
    secret: str,
    *,
    ttl: int = _DEFAULT_TTL,
    now: Optional[float] = None,
) -> str:
    """Return a fresh CSRF token bound to ``session_id``.

    ``ttl=0`` produces a stable token (timestamp ``"0"``) — only use for
    tests. ``now`` is injectable so tests can pin the timestamp.
    """
    if not session_id:
        return ""
    ts = "0" if ttl == 0 else str(int(now if now is not None else time.time()))
    sig = _sign(session_id, ts, secret)
    return f"{ts}:{sig}"


def verify_token(
    token: str,
    session_id: str,
    secret: str,
    *,
    ttl: int = _DEFAULT_TTL,
    now: Optional[float] = None,
) -> bool:
    """Return True iff ``token`` was issued for ``session_id`` under ``secret``
    and is not older than ``ttl`` seconds.
    """
    if not token or not session_id:
        return False
    parsed = _parse_token(token)
    if parsed is None:
        return False
    ts, sig = parsed
    expected = _sign(session_id, ts, secret)
    if not hmac.compare_digest(sig, expected):
        return False
    if ttl <= 0:
        return True
    try:
        issued = int(ts)
    except ValueError:
        return False
    current = int(now if now is not None else time.time())
    return current - issued <= ttl


def _sign(session_id: str, ts: str, secret: str) -> str:
    payload = f"{DOMAIN}:{session_id}:{ts}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return digest[:_SIG_LEN]


def _parse_token(token: str) -> Optional[tuple[str, str]]:
    if ":" not in token:
        return None
    ts, sig = token.split(":", 1)
    if not ts or len(sig) != _SIG_LEN:
        return None
    return ts, sig
