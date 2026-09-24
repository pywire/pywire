"""Child-proxy identity stability on WireList/WireDict (Task 11 Part A).

Keyed ``{$for}`` regions need per-item invalidation keys: child proxies
must be identity-stable across reads so a write through one proxy fires
subscriptions registered by a different read, and item writes must bubble
to the parent under a per-item field (``str(index)``/``str(key)``) instead
of the whole-container ``"value"`` field.
"""

import pytest

from pywire.core.wire import (
    WireDict,
    WireList,
    reset_render_context,
    set_render_context,
    unwrap_wire,
    wire,
)


class _FakePage:
    def __init__(self):
        self.reads = []
        self.invals = []

    def _register_wire_read(self, wire_obj, field, region_id):
        self.reads.append((wire_obj, field, region_id))

    def _invalidate_wire(self, wire_obj, field):
        self.invals.append((wire_obj, field))


def test_list_child_identity_stable_across_reads():
    w = wire([{"a": 1}, {"b": 2}])
    first = w[0]
    second = w[0]
    assert first is second
    assert isinstance(first, WireDict)
    # Iteration yields the same proxy object as indexing.
    assert list(w)[0] is first
    assert next(iter(w)) is first


def test_list_child_write_persists():
    w = wire([{"a": 1}])
    w[0]["a"] = 2
    # Write through the proxy is visible on every subsequent read path.
    assert w[0]["a"] == 2
    assert list(w)[0]["a"] == 2
    assert unwrap_wire(w) == [{"a": 2}]


def test_list_slot_replacement_yields_fresh_proxy():
    w = wire([{"a": 1}])
    old = w[0]
    w[0] = {"a": 999}
    new = w[0]
    assert new is not old
    assert new["a"] == 999


def test_list_structural_ops_keep_identity_consistent():
    w = wire([{"i": 0}, {"i": 1}])
    p0, p1 = w[0], w[1]
    w.append({"i": 2})
    # Existing elements keep their proxies; the new one gets a stable proxy.
    assert w[0] is p0 and w[1] is p1
    assert w[2] is w[2]
    w.pop(0)
    # Identity follows the element, not the position.
    assert w[0] is p1
    w.clear()
    assert len(w) == 0
    w.extend([{"i": 9}])
    assert w[0] is not p1
    assert w[0] is w[0]


def test_list_item_write_bubbles_per_index_field():
    w = wire([{"a": 1}, {"b": 2}])
    page = _FakePage()
    w._pages.add(page)
    child = w[0]
    child["a"] = 5
    assert (w, "0") in page.invals
    # Whole-container "value" is NOT notified for an item-field write, so
    # structural-only subscribers (e.g. the whole-loop region) stay clean.
    assert (w, "value") not in page.invals
    # A structural write still uses the "value" field.
    page.invals.clear()
    w.append({"c": 3})
    assert (w, "value") in page.invals


def test_negative_index_same_proxy_as_positive():
    w = wire([{"a": 1}, {"b": 2}])
    assert w[-1] is w[1]


def test_dict_child_identity_stable_and_write_persists():
    d = wire({"x": {"n": 1}, "y": {"n": 2}})
    c1 = d["x"]
    c2 = d["x"]
    assert c1 is c2
    assert isinstance(c1, WireDict)
    c1["n"] = 5
    assert d["x"]["n"] == 5
    assert unwrap_wire(d) == {"x": {"n": 5}, "y": {"n": 2}}
    # values()/items() yield the same stable proxies
    assert dict(d.items())["x"] is c1
    assert c1 in list(d.values())


def test_dict_item_write_bubbles_per_key_field():
    d = wire({"x": {"n": 1}})
    page = _FakePage()
    d._pages.add(page)
    d["x"]["n"] = 2
    assert (d, "x") in page.invals
    assert (d, "value") not in page.invals


def test_dict_structural_ops_replace_entries():
    d = wire({"x": {"n": 1}})
    old = d["x"]
    d["x"] = {"n": 100}
    assert d["x"] is not old
    assert d["x"]["n"] == 100
    d.pop("x")
    d.setdefault("x", {"n": 7})
    assert d["x"]["n"] == 7
    assert d["x"] is d["x"]


def test_dict_get_is_tracked():
    d = wire({"a": {"x": 1}})
    page = _FakePage()
    d._pages.add(page)
    token = set_render_context(page, "r1")
    try:
        val = d.get("a")
    finally:
        reset_render_context(token)
    assert isinstance(val, WireDict)
    assert val is d["a"]
    assert any(region == "r1" for (_, _, region) in page.reads)


def test_unwrap_wire_returns_raw_containers():
    w = wire([{"a": 1}, [2, 3]])
    raw = unwrap_wire(w)
    assert type(raw) is list
    assert type(raw[0]) is dict
    assert type(raw[1]) is list
    assert raw == [{"a": 1}, [2, 3]]
    d = wire({"x": {"n": 1}})
    raw_d = unwrap_wire(d)
    assert type(raw_d) is dict and type(raw_d["x"]) is dict
    # str() of an unwrapped value never recurses
    assert str(raw_d) == str({"x": {"n": 1}})


def test_frozen_list_children_are_read_only():
    w = wire([{"a": 1}])
    w.freeze()
    child = w[0]  # reading a frozen list must not raise
    with pytest.raises(TypeError):
        child["a"] = 2
    with pytest.raises(TypeError):
        w.append({"b": 2})


def test_freeze_after_proxy_creation_propagates():
    w = wire([{"a": 1}])
    child = w[0]
    w.freeze()
    with pytest.raises(TypeError):
        child["a"] = 2


def test_wirelist_type_preserved():
    w = wire([{"a": 1}])
    assert isinstance(w, WireList)
    assert w == [{"a": 1}]
