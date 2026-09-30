"""HMAC-signed state the client holds: session snapshots in stateless mode,
and smaller pieces a page hands the browser to send back (wizard steps)."""

import base64
import hashlib
import hmac
import logging
import zlib
from typing import Dict, Optional
from urllib.parse import unquote

import msgpack

from pywire.runtime.session_serializer import snapshot_page_state

logger = logging.getLogger(__name__)

_SIG_LEN = 32  # SHA-256

# Ceiling on client-held snapshot blobs (base64 text) before any decode
# work — an oversized blob must be a cheap reject, not a decode burn.
MAX_SNAPSHOT_LEN = 4 * 1024 * 1024
# Ceiling on the inflated msgpack payload. The blob is authenticated before
# it is inflated, so this only bounds what our own server signed.
MAX_SNAPSHOT_RAW_LEN = 64 * 1024 * 1024
# The snapshot travels on every event in both directions, so size beats the
# last bit of speed: level 6 shrinks list state about 10x.
_ZLIB_LEVEL = 6


class SnapshotError(Exception):
    """Raised when a client snapshot is corrupt, tampered, or foreign."""


def snapshot_route(path: str, query: str = "") -> str:
    """Canonical page URL a snapshot is bound to: decoded path + raw query."""
    path = unquote(path)
    return f"{path}?{query}" if query else path


def encode_snapshot(
    page,
    *,
    secret: bytes,
    route: str,
    warn_size: int = 0,
    live: Optional[Dict[str, str]] = None,
) -> str:
    """base64(HMAC-SHA256(body) + body), body = zlib(msgpack(snapshot)).

    ``route`` (from ``snapshot_route``) is signed into the body so the
    stateless endpoint only rebuilds the page the snapshot was rendered for.
    ``live`` maps each shared-state region to a digest of the HTML the client
    shows for it, so a poll can skip regions that haven't changed.
    """
    # Holds no identity (re-resolved per request), only whose state it is.
    snap = snapshot_page_state(page)
    snap["route"] = route
    if live:
        snap["live"] = live
    raw = msgpack.packb(snap)
    if warn_size > 0 and len(raw) > warn_size:
        logger.warning(
            "Stateless snapshot for %s is %d bytes before compression "
            "(threshold: %d). It travels with every event; consider moving "
            "large data out of page attributes.",
            type(page).__qualname__,
            len(raw),
            warn_size,
        )
    return _seal(raw, secret)


def decode_snapshot(blob: str, *, secret: bytes) -> dict:
    return verify(blob, secret=secret)


def sign(data: dict, *, secret: bytes) -> str:
    """``data`` as a signed blob the client can hold but not change.

    Signed, not encrypted: whoever holds the blob can read it.
    """
    return _seal(msgpack.packb(data), secret)


def _seal(raw: bytes, secret: bytes) -> str:
    body = zlib.compress(raw, _ZLIB_LEVEL)
    sig = hmac.new(secret, body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig + body).decode("ascii")


def verify(blob: str, *, secret: bytes) -> dict:
    """The mapping a blob from :func:`sign` holds; ``SnapshotError`` if forged."""
    if not isinstance(blob, str) or len(blob) > MAX_SNAPSHOT_LEN:
        raise SnapshotError("malformed snapshot encoding")
    try:
        data = base64.urlsafe_b64decode(blob.encode("ascii"))
    except Exception as exc:
        raise SnapshotError("malformed snapshot encoding") from exc
    if len(data) <= _SIG_LEN:
        raise SnapshotError("snapshot too short")
    sig, body = data[:_SIG_LEN], data[_SIG_LEN:]
    expected = hmac.new(secret, body, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise SnapshotError("snapshot signature mismatch")
    try:
        inflater = zlib.decompressobj()
        raw = inflater.decompress(body, MAX_SNAPSHOT_RAW_LEN)
        if inflater.unconsumed_tail or not inflater.eof:
            raise SnapshotError("snapshot payload too large or truncated")
    except zlib.error as exc:
        raise SnapshotError("snapshot payload corrupt") from exc
    try:
        snap = msgpack.unpackb(raw, raw=False)
    except Exception as exc:
        raise SnapshotError("snapshot payload corrupt") from exc
    if not isinstance(snap, dict):
        raise SnapshotError("snapshot payload not a mapping")
    return snap
