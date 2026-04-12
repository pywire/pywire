"""Tests for session state serialization."""

from unittest.mock import MagicMock

from pywire.core.wire import (
    WirePrimitive,
    wire,
)
from pywire.runtime.page import BasePage
from pywire.runtime.session_serializer import (
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


def _make_page(**attrs):
    """Create a BasePage with user-defined attributes."""
    page = BasePage(_make_request(), {}, {})
    for name, value in attrs.items():
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

    def test_errors_and_loading(self):
        page = _make_page()
        page.errors = {"email": "invalid"}
        page.loading = {"fetch": True}
        snap = snapshot_page_state(page)
        assert snap["errors"] == {"email": "invalid"}
        assert snap["loading"] == {"fetch": True}

    def test_user_serializable(self):
        page = _make_page()
        page.user = {"id": 1, "name": "test"}
        snap = snapshot_page_state(page)
        assert snap["user"] == {"id": 1, "name": "test"}

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
        assert snap["page_class"] == "BasePage"
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
        restore_page_state(page, snap)
        assert page.count.peek() == 42

    def test_restore_list_wire(self):
        page = _make_page(items=wire([]))
        snap = {
            "attrs": {"items": [1, 2, 3]},
            "wire_tags": {"items": "list"},
        }
        restore_page_state(page, snap)
        assert list(page.items) == [1, 2, 3]

    def test_restore_dict_wire(self):
        page = _make_page(data=wire({}))
        snap = {
            "attrs": {"data": {"a": 1}},
            "wire_tags": {"data": "dict"},
        }
        restore_page_state(page, snap)
        assert dict(page.data) == {"a": 1}

    def test_restore_set_wire(self):
        page = _make_page(tags=wire(set()))
        snap = {
            "attrs": {"tags": ["x", "y"]},
            "wire_tags": {"tags": "set"},
        }
        restore_page_state(page, snap)
        assert set(page.tags) == {"x", "y"}

    def test_restore_namespace_wire(self):
        page = _make_page(pos=wire(x=0, y=0))
        snap = {
            "attrs": {"pos": {"x": 10, "y": 20}},
            "wire_tags": {"pos": "namespace"},
        }
        restore_page_state(page, snap)
        assert page.pos.peek() == {"x": 10, "y": 20}

    def test_restore_plain_attr(self):
        page = _make_page(title="old")
        snap = {"attrs": {"title": "new"}, "wire_tags": {}}
        restore_page_state(page, snap)
        assert page.title == "new"

    def test_restore_new_wire_attr(self):
        """If the page class doesn't have the wire yet, create it."""
        page = _make_page()
        snap = {
            "attrs": {"count": 5},
            "wire_tags": {"count": "primitive"},
        }
        restore_page_state(page, snap)
        assert isinstance(page.count, WirePrimitive)
        assert page.count.peek() == 5

    def test_restore_errors_and_loading(self):
        page = _make_page()
        snap = {
            "attrs": {},
            "wire_tags": {},
            "errors": {"email": "required"},
            "loading": {"save": True},
        }
        restore_page_state(page, snap)
        assert page.errors == {"email": "required"}
        assert page.loading == {"save": True}

    def test_restore_user(self):
        page = _make_page()
        snap = {
            "attrs": {},
            "wire_tags": {},
            "user": {"id": 1, "name": "Alice"},
        }
        restore_page_state(page, snap)
        assert page.user == {"id": 1, "name": "Alice"}

    def test_restore_await_states(self):
        page = _make_page()
        snap = {
            "attrs": {},
            "wire_tags": {},
            "await_states": {
                "a1": {"status": "pending", "result": None, "error": None}
            },
        }
        restore_page_state(page, snap)
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
        restore_page_state(page, snap)
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
        page1.errors = {"field": "error"}
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
        restore_page_state(page2, snap1)

        # Verify state matches
        assert page2.count.peek() == 42
        assert list(page2.items) == ["a", "b", "c"]
        assert dict(page2.data) == {"key": "value"}
        assert page2.title == "My Page"
        assert page2.flag is True
        assert page2.errors == {"field": "error"}
        assert page2.loading == {"action": True}
        assert page2.user == {"id": 1}

        # Snapshot again and compare
        snap2 = snapshot_page_state(page2)
        assert snap1["attrs"] == snap2["attrs"]
        assert snap1["wire_tags"] == snap2["wire_tags"]
        assert snap1["errors"] == snap2["errors"]
        assert snap1["loading"] == snap2["loading"]

    def test_round_trip_with_set(self):
        page1 = _make_page(tags=wire({"a", "b", "c"}))
        snap1 = snapshot_page_state(page1)

        page2 = _make_page(tags=wire(set()))
        restore_page_state(page2, snap1)

        # Sets are serialized as lists, so compare as sets
        assert set(page2.tags) == {"a", "b", "c"}
