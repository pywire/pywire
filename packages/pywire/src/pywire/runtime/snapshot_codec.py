"""Sealed state the client holds: session snapshots in stateless mode, and
smaller pieces a page hands the browser to send back (wizard steps).

Every blob is encrypted and authenticated with keys derived from the app's
secret: the browser can hold it and send it back, but can't read or change
it. (The standard library has no block cipher, so the stream is SHAKE-256
keyed with the secret and a fresh nonce, then HMAC-SHA256 over nonce and
ciphertext: encrypt-then-MAC.)
"""

import base64
import functools
import hashlib
import hmac
import logging
import os
import time
import zlib
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote

import msgpack

from pywire.runtime.session_serializer import (
    plain_attr_digest,
    snapshot_page_state,
)

logger = logging.getLogger(__name__)

_SIG_LEN = 32  # SHA-256
_NONCE_LEN = 16
# First byte of every sealed blob; bump it when the format changes.
_FORMAT = b"\x02"
# How long a stateless snapshot is accepted after the server issued it. Every
# response carries a fresh one, so only a page left idle this long reloads.
SNAPSHOT_MAX_AGE = 12 * 60 * 60

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
    snap = snapshot_page_state(page)
    # Never trust the client with identity — re-resolved per request.
    snap.pop("user", None)
    _drop_initial_values(page, snap)
    snap["route"] = route
    # Issued-at, and who it was issued to: a snapshot is only accepted for a
    # while, and only for the same signed-in user.
    snap["iat"] = int(time.time())
    snap["sub"] = snapshot_subject(page)
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


def snapshot_subject(page: Any) -> str:
    """Who a snapshot belongs to: the signed-in user's id, or "" if anonymous."""
    user = getattr(page, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return ""
    return str(getattr(user, "user_id", "") or "")


def _drop_initial_values(page: Any, snap: Dict[str, Any]) -> None:
    """Leave out plain attributes still holding what the page's code set up.

    Rebuilding the page runs its frontmatter again, which recreates them, so
    they needn't travel, and frontmatter often holds what the browser must
    not see (an API key read from the environment, a config object). Only
    values an ``@init`` hook or a handler changed are carried.
    """
    initial = page.__dict__.get("_pw_initial_digests")
    attrs = snap.get("attrs")
    if not isinstance(initial, dict) or not isinstance(attrs, dict):
        return
    wires = snap.get("wire_tags") or {}
    for name in list(attrs):
        if name not in wires and initial.get(name) == plain_attr_digest(attrs[name]):
            del attrs[name]


def decode_snapshot(
    blob: str, *, secret: bytes, max_age: int = SNAPSHOT_MAX_AGE
) -> dict:
    """The snapshot in ``blob``; ``SnapshotError`` if forged or expired."""
    snap = verify(blob, secret=secret)
    issued = snap.get("iat")
    now = time.time()
    if not isinstance(issued, int) or not now - max_age <= issued <= now + 60:
        raise SnapshotError("snapshot expired")
    return snap


def sign(data: dict, *, secret: bytes) -> str:
    """``data`` as a sealed blob the client can hold but not read or change."""
    return _seal(msgpack.packb(data), secret)


@functools.lru_cache(maxsize=8)
def _keys(secret: bytes) -> Tuple[bytes, bytes]:
    """(encryption key, MAC key), derived so neither is the raw secret."""
    enc = hmac.new(secret, b"pywire.sealed.enc", hashlib.sha256).digest()
    mac = hmac.new(secret, b"pywire.sealed.mac", hashlib.sha256).digest()
    return enc, mac


def _xor_stream(key: bytes, nonce: bytes, data: bytes) -> bytes:
    stream = hashlib.shake_256(key + nonce).digest(len(data))
    mixed = int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")
    return mixed.to_bytes(len(data), "big")


def _seal(raw: bytes, secret: bytes) -> str:
    enc, mac = _keys(secret)
    nonce = os.urandom(_NONCE_LEN)
    body = _xor_stream(enc, nonce, zlib.compress(raw, _ZLIB_LEVEL))
    sig = hmac.new(mac, _FORMAT + nonce + body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(_FORMAT + sig + nonce + body).decode("ascii")


def verify(blob: str, *, secret: bytes) -> dict:
    """The mapping a blob from :func:`sign` holds; ``SnapshotError`` if forged."""
    if not isinstance(blob, str) or len(blob) > MAX_SNAPSHOT_LEN:
        raise SnapshotError("malformed snapshot encoding")
    try:
        data = base64.urlsafe_b64decode(blob.encode("ascii"))
    except Exception as exc:
        raise SnapshotError("malformed snapshot encoding") from exc
    if len(data) <= 1 + _SIG_LEN + _NONCE_LEN or data[:1] != _FORMAT:
        raise SnapshotError("snapshot too short or of another format")
    sig = data[1 : 1 + _SIG_LEN]
    nonce = data[1 + _SIG_LEN : 1 + _SIG_LEN + _NONCE_LEN]
    sealed = data[1 + _SIG_LEN + _NONCE_LEN :]
    enc, mac = _keys(secret)
    expected = hmac.new(mac, _FORMAT + nonce + sealed, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise SnapshotError("snapshot signature mismatch")
    body = _xor_stream(enc, nonce, sealed)
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
