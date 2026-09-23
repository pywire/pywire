import base64
import pytest
from pywire import wire
from pywire.runtime.snapshot_codec import encode_snapshot, decode_snapshot, SnapshotError

SECRET = b"test-secret-key"

class _FakePage:
    pass

def make_page():
    p = _FakePage()
    p.count = wire(7)
    p.user = {"id": "u1", "token": "bearer-xyz"}
    p.errors = {}; p.loading = {}; p._components = {}; p._await_states = {}
    p.request = None
    return p

def test_round_trip():
    blob = encode_snapshot(make_page(), secret=SECRET)
    assert decode_snapshot(blob, secret=SECRET)["attrs"]["count"] == 7

def test_user_never_in_snapshot():
    snap = decode_snapshot(encode_snapshot(make_page(), secret=SECRET), secret=SECRET)
    assert "user" not in snap

def test_tampered_snapshot_rejected():
    blob = encode_snapshot(make_page(), secret=SECRET)
    raw = bytearray(base64.urlsafe_b64decode(blob))
    raw[-1] ^= 0xFF
    with pytest.raises(SnapshotError):
        decode_snapshot(base64.urlsafe_b64encode(bytes(raw)).decode(), secret=SECRET)

def test_wrong_secret_rejected():
    blob = encode_snapshot(make_page(), secret=SECRET)
    with pytest.raises(SnapshotError):
        decode_snapshot(blob, secret=b"other-secret")

def test_garbage_rejected():
    for bad in ("", "!!!", base64.urlsafe_b64encode(b"short").decode()):
        with pytest.raises(SnapshotError):
            decode_snapshot(bad, secret=SECRET)

def test_large_state_round_trips():
    p = make_page()
    p.big = wire([{"row": i, "name": f"item-{i}"} for i in range(5000)])
    blob = encode_snapshot(p, secret=SECRET, warn_size=1024)
    assert len(decode_snapshot(blob, secret=SECRET)["attrs"]["big"]) == 5000