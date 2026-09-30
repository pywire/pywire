import base64
import pytest
from pywire import wire
from pywire.runtime.snapshot_codec import (
    encode_snapshot,
    decode_snapshot,
    snapshot_route,
    SnapshotError,
)

SECRET = b"test-secret-key"


class _FakePage:
    pass


def make_page():
    p = _FakePage()
    p.count = wire(7)
    p.user = {"id": "u1", "token": "bearer-xyz"}
    p.loading = {}
    p._components = {}
    p._await_states = {}
    p.request = None
    return p


def test_round_trip():
    blob = encode_snapshot(make_page(), secret=SECRET, route="/")
    assert decode_snapshot(blob, secret=SECRET)["attrs"]["count"] == 7


def test_route_is_signed_into_snapshot():
    blob = encode_snapshot(make_page(), secret=SECRET, route="/orgs/1?tab=a")
    assert decode_snapshot(blob, secret=SECRET)["route"] == "/orgs/1?tab=a"


def test_snapshot_route_canonical_form():
    # Browsers send percent-encoded paths; servers see them decoded.
    assert snapshot_route("/users/j%C3%B6rg") == snapshot_route("/users/j\u00f6rg")
    assert snapshot_route("/a", "x=1") == "/a?x=1"
    assert snapshot_route("/a", "") == "/a"


def test_user_never_in_snapshot():
    snap = decode_snapshot(
        encode_snapshot(make_page(), secret=SECRET, route="/"), secret=SECRET
    )
    assert "user" not in snap


def test_tampered_snapshot_rejected():
    blob = encode_snapshot(make_page(), secret=SECRET, route="/")
    raw = bytearray(base64.urlsafe_b64decode(blob))
    raw[-1] ^= 0xFF
    with pytest.raises(SnapshotError):
        decode_snapshot(base64.urlsafe_b64encode(bytes(raw)).decode(), secret=SECRET)


def test_wrong_secret_rejected():
    blob = encode_snapshot(make_page(), secret=SECRET, route="/")
    with pytest.raises(SnapshotError):
        decode_snapshot(blob, secret=b"other-secret")


def test_garbage_rejected():
    for bad in ("", "!!!", base64.urlsafe_b64encode(b"short").decode()):
        with pytest.raises(SnapshotError):
            decode_snapshot(bad, secret=SECRET)


def test_large_state_round_trips():
    p = make_page()
    p.big = wire([{"row": i, "name": f"item-{i}"} for i in range(5000)])
    blob = encode_snapshot(p, secret=SECRET, route="/", warn_size=1024)
    assert len(decode_snapshot(blob, secret=SECRET)["attrs"]["big"]) == 5000


def test_snapshot_is_compressed():
    import msgpack

    from pywire.runtime.session_serializer import snapshot_page_state

    p = make_page()
    p.rows = wire([{"name": f"item-{i}", "done": False} for i in range(1000)])
    blob = encode_snapshot(p, secret=SECRET, route="/")
    raw = msgpack.packb(snapshot_page_state(p))

    assert len(blob) * 5 < len(raw)
    assert len(decode_snapshot(blob, secret=SECRET)["attrs"]["rows"]) == 1000


def _seal_body(body: bytes) -> str:
    """A blob sealed with SECRET around an already-compressed ``body``."""
    import hashlib
    import hmac

    from pywire.runtime import snapshot_codec as codec

    enc, mac = codec._keys(SECRET)
    nonce = b"\1" * codec._NONCE_LEN
    sealed = codec._xor_stream(enc, nonce, body)
    sig = hmac.new(mac, codec._FORMAT + nonce + sealed, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(codec._FORMAT + sig + nonce + sealed).decode()


def test_signed_but_corrupt_body_rejected():
    with pytest.raises(SnapshotError, match="corrupt"):
        decode_snapshot(_seal_body(b"not zlib at all"), secret=SECRET)


def test_inflated_size_is_capped(monkeypatch):
    import zlib

    from pywire.runtime import snapshot_codec

    monkeypatch.setattr(snapshot_codec, "MAX_SNAPSHOT_RAW_LEN", 1024)
    with pytest.raises(SnapshotError, match="too large"):
        decode_snapshot(_seal_body(zlib.compress(b"\0" * 100_000)), secret=SECRET)


def test_snapshot_is_encrypted():
    import zlib

    p = make_page()
    p.note = wire("a-distinctive-plaintext-value")
    blob = encode_snapshot(p, secret=SECRET, route="/")
    data = base64.urlsafe_b64decode(blob)
    assert b"distinctive" not in data
    for start in range(len(data)):
        try:
            assert b"distinctive" not in zlib.decompress(data[start:])
        except zlib.error:
            pass
    # A fresh nonce each time: the same state never seals the same way.
    assert encode_snapshot(p, secret=SECRET, route="/") != blob


def test_expired_snapshot_rejected(monkeypatch):
    import time

    blob = encode_snapshot(make_page(), secret=SECRET, route="/")
    assert decode_snapshot(blob, secret=SECRET, max_age=60)
    later = time.time() + 61
    monkeypatch.setattr(time, "time", lambda: later)
    with pytest.raises(SnapshotError, match="expired"):
        decode_snapshot(blob, secret=SECRET, max_age=60)


def test_initial_plain_values_stay_on_the_server():
    from pywire.runtime.session_serializer import remember_initial_state

    p = make_page()
    p.api_key = "sk_live_do_not_leak"
    p.config = {"db": "postgres://secret"}
    p.picked = "none"
    remember_initial_state(p)
    p.picked = "row-3"  # a handler changed it: it must travel
    snap = decode_snapshot(encode_snapshot(p, secret=SECRET, route="/"), secret=SECRET)
    assert "api_key" not in snap["attrs"] and "config" not in snap["attrs"]
    assert snap["attrs"]["picked"] == "row-3"
    assert snap["attrs"]["count"] == 7  # wires always travel
