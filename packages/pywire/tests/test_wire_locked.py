from pywire import wire
from pywire.runtime.page import BasePage
from pywire.runtime.session_serializer import restore_page_state, snapshot_page_state


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


def test_locked_wire_survives_page_restore():
    # Stale signed snapshot from before .lock() was added still carries the
    # attr — restore must skip it so the fresh frontmatter value wins.
    p = make_page()
    snap = {
        "attrs": {"public": 5, "token": "sk-stale-rotated"},
        "wire_tags": {"public": "primitive", "token": "primitive"},
    }
    restore_page_state(p, snap)
    assert p.public.value == 5
    assert p.token.value == "sk-secret"
    assert p.token._locked


def test_locked_wire_survives_component_restore():
    class _Page(BasePage):
        pass

    class _Card(BasePage):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.token = wire("sk-secret").lock()
            self.count = wire(0)

    def _request():
        from starlette.requests import Request

        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/",
                "raw_path": b"/",
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 0),
                "server": ("testserver", 80),
                "scheme": "http",
                "root_path": "",
                "http_version": "1.1",
            }
        )

    page = _Page(_request(), {}, {})
    # restore_page_state rebuilds component snapshot values as fresh UNLOCKED
    # wires — applying them must not clobber (and unlock) the locked wire.
    page._component_state_snapshots["card"] = {
        "token": wire("sk-stale-rotated"),
        "count": wire(7),
    }
    comp = page._resolve_component(
        "card", _Card, request=_request(), params={}, query={}
    )
    assert comp.count.value == 7
    assert comp.token.value == "sk-secret"
    assert comp.token._locked
