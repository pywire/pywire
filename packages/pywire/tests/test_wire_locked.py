from pywire import wire
from pywire.runtime.session_serializer import snapshot_page_state


class _FakePage:
    pass


def make_page():
    p = _FakePage()
    p.public = wire(1)
    p.token = wire("sk-secret").lock()
    p.errors = {}
    p.loading = {}
    p._components = {}
    p._await_states = {}
    return p


def test_locked_wire_excluded_from_snapshot():
    snap = snapshot_page_state(make_page())
    assert snap["attrs"]["public"] == 1
    assert "token" not in snap["attrs"]
    assert "token" not in snap["wire_tags"]


def test_locked_wire_keeps_value_in_process():
    p = make_page()
    assert p.token.value == "sk-secret"  # lock() hides from snapshots only