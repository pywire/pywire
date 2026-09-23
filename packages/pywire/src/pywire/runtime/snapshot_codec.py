"""HMAC-signed session snapshots for stateless (client-held state) mode."""

import base64
import hashlib
import hmac
import logging

import msgpack

from pywire.runtime.session_serializer import snapshot_page_state

logger = logging.getLogger(__name__)

_SIG_LEN = 32  # SHA-256


class SnapshotError(Exception):
    """Raised when a client snapshot is corrupt, tampered, or foreign."""


def encode_snapshot(page, *, secret: bytes, warn_size: int = 0) -> str:
    snap = snapshot_page_state(page, warn_size=warn_size)
    # Never trust the client with identity — re-resolved per request.
    snap.pop("user", None)
    raw = msgpack.packb(snap)
    sig = hmac.new(secret, raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig + raw).decode("ascii")


def decode_snapshot(blob: str, *, secret: bytes) -> dict:
    try:
        data = base64.urlsafe_b64decode(blob.encode("ascii"))
    except Exception as exc:
        raise SnapshotError("malformed snapshot encoding") from exc
    if len(data) <= _SIG_LEN:
        raise SnapshotError("snapshot too short")
    sig, raw = data[:_SIG_LEN], data[_SIG_LEN:]
    expected = hmac.new(secret, raw, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise SnapshotError("snapshot signature mismatch")
    try:
        snap = msgpack.unpackb(raw, raw=False)
    except Exception as exc:
        raise SnapshotError("snapshot payload corrupt") from exc
    if not isinstance(snap, dict):
        raise SnapshotError("snapshot payload not a mapping")
    return snap