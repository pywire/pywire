"""Tests for session state serialization."""

from unittest.mock import MagicMock

from pywire.core.wire import (
    WireBase,
    WirePrimitive,
    wire,
)
from pywire.runtime.page import BasePage
from pywire.runtime.session_serializer import (
    page_identity,
    page_state_key,
    principal_key,
    restore_page_state,
    snapshot_page_state,
)


def _make_request():
    """Create a mock request suitable for BasePage."""
    scope = {
        "type": "http",
        "path": "/test",
        "headers": [],
        "query_string": b"",
        "method": "GET",
    }
    return MagicMock(
        scope=scope,
        url=MagicMock(path="/test"),
        query_params={},
        headers={},
    )


def _restore(page, snap, principal=None):
    """Restore a hand-built snapshot as if taken from ``page``."""
    return restore_page_state(
        page,
        {"page": page_identity(page), **snap},
        principal=principal,
    )


def _make_page(**attrs):
    """Create a BasePage with user-defined attributes."""
    page = BasePage(_make_request(), {}, {})
    for name, value in attrs.items():
        if isinstance(value, WireBase):
            # Page state, as if the page's frontmatter had created it.
            value._owner = page._owner_token
        setattr(page, name, value)
    return page


class TestSnapshotPageState:
    def test_primitive_wire(self):
        page = _make_page(count=wire(42))
        snap = snapshot_page_state(page)
        assert snap["attrs"]["count"] == 42
        assert snap["wire_tags"]["count"] == "primitive"

    def test_list_wire(self):
        page = _make_page(items=wire([1, 2, 3]))
        snap = snapshot_page_state(page)
        assert snap["attrs"]["items"] == [1, 2, 3]
        assert snap["wire_tags"]["items"] == "list"

    def test_dict_wire(self):
        page = _make_page(data=wire({"a": 1, "b": 2}))
        snap = snapshot_page_state(page)
        assert snap["attrs"]["data"] == {"a": 1, "b": 2}
        assert snap["wire_tags"]["data"] == "dict"

    def test_set_wire(self):
        page = _make_page(tags=wire({"x", "y"}))
        snap = snapshot_page_state(page)
        # Sets are serialized as lists
        assert set(snap["attrs"]["tags"]) == {"x", "y"}
        assert snap["wire_tags"]["tags"] == "set"

    def test_namespace_wire(self):
        page = _make_page(pos=wire(x=10, y=20))
        snap = snapshot_page_state(page)
        assert snap["attrs"]["pos"] == {"x": 10, "y": 20}
        assert snap["wire_tags"]["pos"] == "namespace"

    def test_plain_attr(self):
        page = _make_page(name="hello", age=25)
        snap = snapshot_page_state(page)
        assert snap["attrs"]["name"] == "hello"
        assert snap["attrs"]["age"] == 25
        assert "name" not in snap["wire_tags"]
        assert "age" not in snap["wire_tags"]

    def test_skips_private_attrs(self):
        page = _make_page()
        page._secret = "hidden"
        snap = snapshot_page_state(page)
        assert "_secret" not in snap["attrs"]

    def test_skips_framework_attrs(self):
        page = _make_page()
        snap = snapshot_page_state(page)
        for attr in ["request", "params", "query", "path", "url", "slots"]:
            assert attr not in snap["attrs"]

    def test_loading(self):
        page = _make_page()
        page.loading = {"fetch": True}
        snap = snapshot_page_state(page)
        assert snap["loading"] == {"fetch": True}

    def test_user_never_in_snapshot(self):
        page = _make_page()
        page.user = {"id": 1, "name": "Alice"}
        snap = snapshot_page_state(page)
        assert "user" not in snap
        assert "Alice" not in repr(snap)
        assert snap["principal"] == principal_key({"id": 1, "name": "Alice"})

    def test_user_none(self):
        page = _make_page()
        snap = snapshot_page_state(page)
        assert "user" not in snap

    def test_non_serializable_attr_skipped(self):
        page = _make_page()
        page.db_conn = object()  # Not serializable
        page.name = "test"
        snap = snapshot_page_state(page)
        assert "db_conn" not in snap["attrs"]
        assert snap["attrs"]["name"] == "test"

    def test_page_class_and_route_path(self):
        page = _make_page()
        snap = snapshot_page_state(page)
        assert snap["page"] == page_identity(page)
        assert snap["route_path"] == "/test"

    def test_await_states(self):
        page = _make_page()
        page._await_states = {"a1": {"status": "success", "result": 42, "error": None}}
        snap = snapshot_page_state(page)
        assert snap["await_states"] == {
            "a1": {"status": "success", "result": 42, "error": None}
        }

    def test_mixed_wire_and_plain(self):
        page = _make_page(
            count=wire(0),
            items=wire(["a", "b"]),
            title="My Page",
            flag=True,
        )
        snap = snapshot_page_state(page)
        assert snap["attrs"]["count"] == 0
        assert snap["attrs"]["items"] == ["a", "b"]
        assert snap["attrs"]["title"] == "My Page"
        assert snap["attrs"]["flag"] is True
        assert snap["wire_tags"] == {"count": "primitive", "items": "list"}


class TestRestorePageState:
    def test_restore_primitive_wire(self):
        page = _make_page(count=wire(0))
        snap = {
            "attrs": {"count": 42},
            "wire_tags": {"count": "primitive"},
        }
        _restore(page, snap)
        assert page.count.peek() == 42

    def test_restore_list_wire(self):
        page = _make_page(items=wire([]))
        snap = {
            "attrs": {"items": [1, 2, 3]},
            "wire_tags": {"items": "list"},
        }
        _restore(page, snap)
        assert list(page.items) == [1, 2, 3]

    def test_restore_dict_wire(self):
        page = _make_page(data=wire({}))
        snap = {
            "attrs": {"data": {"a": 1}},
            "wire_tags": {"data": "dict"},
        }
        _restore(page, snap)
        assert dict(page.data) == {"a": 1}

    def test_restore_set_wire(self):
        page = _make_page(tags=wire(set()))
        snap = {
            "attrs": {"tags": ["x", "y"]},
            "wire_tags": {"tags": "set"},
        }
        _restore(page, snap)
        assert set(page.tags) == {"x", "y"}

    def test_restore_namespace_wire(self):
        page = _make_page(pos=wire(x=0, y=0))
        snap = {
            "attrs": {"pos": {"x": 10, "y": 20}},
            "wire_tags": {"pos": "namespace"},
        }
        _restore(page, snap)
        assert page.pos.peek() == {"x": 10, "y": 20}

    def test_restore_plain_attr(self):
        page = _make_page(title="old")
        snap = {"attrs": {"title": "new"}, "wire_tags": {}}
        _restore(page, snap)
        assert page.title == "new"

    def test_restore_new_wire_attr(self):
        """If the page class doesn't have the wire yet, create it."""
        page = _make_page()
        snap = {
            "attrs": {"count": 5},
            "wire_tags": {"count": "primitive"},
        }
        _restore(page, snap)
        assert isinstance(page.count, WirePrimitive)
        assert page.count.peek() == 5

    def test_restore_loading(self):
        page = _make_page()
        snap = {
            "attrs": {},
            "wire_tags": {},
            "loading": {"save": True},
        }
        _restore(page, snap)
        assert page.loading == {"save": True}

    def test_restore_never_sets_user(self):
        page = _make_page()
        snap = {
            "attrs": {},
            "wire_tags": {},
            "user": {"id": 1, "name": "Alice"},
        }
        _restore(page, snap)
        assert page.user is None

    def test_restore_await_states(self):
        page = _make_page()
        snap = {
            "attrs": {},
            "wire_tags": {},
            "await_states": {
                "a1": {"status": "pending", "result": None, "error": None}
            },
        }
        _restore(page, snap)
        assert page._await_states == {
            "a1": {"status": "pending", "result": None, "error": None}
        }

    def test_restore_component_snapshots(self):
        page = _make_page()
        snap = {
            "attrs": {},
            "wire_tags": {},
            "component_snapshots": {
                "counter-1": {
                    "count": {"value": 10, "wire_tag": "primitive"},
                    "label": {"value": "clicks"},
                },
            },
        }
        _restore(page, snap)
        assert "counter-1" in page._component_state_snapshots
        comp = page._component_state_snapshots["counter-1"]
        assert isinstance(comp["count"], WirePrimitive)
        assert comp["count"].peek() == 10
        assert comp["label"] == "clicks"


class TestRoundTrip:
    """Test snapshot -> restore -> snapshot produces equivalent state."""

    def test_full_round_trip(self):
        # Create a page with various state
        page1 = _make_page(
            count=wire(42),
            items=wire(["a", "b", "c"]),
            data=wire({"key": "value"}),
            title="My Page",
            flag=True,
        )
        page1.loading = {"action": True}
        page1.user = {"id": 1}

        # Snapshot
        snap1 = snapshot_page_state(page1)

        # Create a fresh page and restore
        page2 = _make_page(
            count=wire(0),
            items=wire([]),
            data=wire({}),
            title="",
            flag=False,
        )
        assert restore_page_state(page2, snap1, principal={"id": 1})

        # Verify state matches
        assert page2.count.peek() == 42
        assert list(page2.items) == ["a", "b", "c"]
        assert dict(page2.data) == {"key": "value"}
        assert page2.title == "My Page"
        assert page2.flag is True
        assert page2.loading == {"action": True}
        # Identity is the request's, never the snapshot's
        assert page2.user is None

        # Snapshot again and compare
        snap2 = snapshot_page_state(page2)
        assert snap1["attrs"] == snap2["attrs"]
        assert snap1["wire_tags"] == snap2["wire_tags"]
        assert snap1["loading"] == snap2["loading"]

    def test_round_trip_with_set(self):
        page1 = _make_page(tags=wire({"a", "b", "c"}))
        snap1 = snapshot_page_state(page1)

        page2 = _make_page(tags=wire(set()))
        restore_page_state(page2, snap1, principal=None)

        # Sets are serialized as lists, so compare as sets
        assert set(page2.tags) == {"a", "b", "c"}


class TestSharedWires:
    """A wire the page didn't create (a module-level wire aliased onto it) is
    shared by every user: never snapshotted, never restored from a snapshot."""

    def test_shared_wire_not_snapshotted(self):
        shared = wire(3)
        page = _make_page(count=wire(1))
        page.votes = shared
        snap = snapshot_page_state(page)
        assert snap["attrs"]["count"] == 1
        assert "votes" not in snap["attrs"]
        assert "votes" not in snap["wire_tags"]

    def test_shared_wire_not_restored(self):
        shared = wire(3)
        page = _make_page()
        page.votes = shared
        _restore(page, {"attrs": {"votes": 0}, "wire_tags": {"votes": "primitive"}})
        assert shared.value == 3

    def test_wires_created_by_page_construction_are_owned(self):
        class _Page(BasePage):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.count = wire(5)

        page = _Page(_make_request(), {}, {})
        assert snapshot_page_state(page)["attrs"]["count"] == 5


class _OtherPage(BasePage):
    pass


class TestSnapshotOwnership:
    """A snapshot restores only into the page it was taken from, for the
    user it was taken for (H4)."""

    def test_other_page_class_is_refused(self):
        page = _make_page(note=wire("secret-A"))
        snap = snapshot_page_state(page)
        other = _OtherPage(_make_request(), {}, {})
        other.note = wire("public-B")
        other.note._owner = other._owner_token
        assert restore_page_state(other, snap, principal=None) is False
        assert other.note.peek() == "public-B"

    def test_other_user_is_refused(self):
        page = _make_page(note=wire("alice's draft"))
        page.user = {"id": "alice"}
        snap = snapshot_page_state(page)
        fresh = _make_page(note=wire(""))
        assert restore_page_state(fresh, snap, principal={"id": "bob"}) is False
        assert restore_page_state(fresh, snap, principal=None) is False
        assert fresh.note.peek() == ""
        assert restore_page_state(fresh, snap, principal={"id": "alice"})
        assert fresh.note.peek() == "alice's draft"

    def test_snapshot_without_owner_is_refused(self):
        page = _make_page(count=wire(0))
        assert (
            restore_page_state(
                page,
                {"attrs": {"count": 9}, "wire_tags": {"count": "primitive"}},
                principal=None,
            )
            is False
        )
        assert page.count.peek() == 0

    def test_each_page_of_a_session_has_its_own_key(self):
        page = _make_page()
        other_route = _make_page()
        other_route.request.url.path = "/other"
        other_class = _OtherPage(_make_request(), {}, {})
        keys = {
            page_state_key("s1", page),
            page_state_key("s1", other_route),
            page_state_key("s1", other_class),
            page_state_key("s2", page),
        }
        assert len(keys) == 4
        assert page_state_key("s1", page) == page_state_key("s1", _make_page())
