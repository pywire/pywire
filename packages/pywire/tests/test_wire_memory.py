"""Row proxies stay out of snapshots and keep per-row bookkeeping small (#330)."""

from weakref import ReferenceType, WeakSet

from pywire import wire
from pywire.core.wire import WireBase, reset_render_context, set_render_context
from pywire.runtime.session_serializer import snapshot_page_state


class _Reader:
    """Records the reads and invalidations a page would receive."""

    def __init__(self) -> None:
        self.reads: list = []
        self.invals: list = []

    def _register_wire_read(self, wire_obj, field, region_id) -> None:
        self.reads.append((wire_obj, field, region_id))

    def _invalidate_wire(self, wire_obj, field) -> None:
        self.invals.append((wire_obj, field))


def _contains_wire(value) -> bool:
    if isinstance(value, WireBase):
        return True
    if isinstance(value, dict):
        return any(_contains_wire(v) for v in value.values())
    if isinstance(value, (list, set, tuple)):
        return any(_contains_wire(v) for v in value)
    return False


def test_peek_returns_plain_copies_after_rows_were_proxied() -> None:
    rows = wire([{"name": "a", "tags": ["x"]}, {"name": "b", "tags": []}])
    for row in rows:  # iteration stores a proxy in every slot
        assert isinstance(row, WireBase)

    plain = rows.peek()

    assert plain == [{"name": "a", "tags": ["x"]}, {"name": "b", "tags": []}]
    assert not _contains_wire(plain)
    plain[0]["name"] = "changed"
    assert rows.peek()[0]["name"] == "a"  # a copy, not live state


def test_peek_does_not_register_reads_or_create_proxies() -> None:
    rows = wire([{"name": "a"}, {"name": "b"}])
    page = _Reader()
    token = set_render_context(page, "r0")
    try:
        rows.peek()
        wire({"k": {"nested": 1}}).peek()
        wire({1, 2}).peek()
    finally:
        reset_render_context(token)

    assert page.reads == []
    assert not any(isinstance(v, WireBase) for v in list.__iter__(rows))


def test_session_snapshot_holds_no_live_proxies() -> None:
    class Page:
        def __init__(self) -> None:
            self.items = wire([{"name": "a", "done": False}])
            self.errors: dict = {}
            self.loading: dict = {}

    page = Page()
    list(page.items)  # proxy the rows, as a render does

    snapshot = snapshot_page_state(page)

    assert snapshot["attrs"]["items"] == [{"name": "a", "done": False}]
    assert not _contains_wire(snapshot)


def test_one_reader_is_a_weakref_and_a_second_upgrades_to_a_weakset() -> None:
    w = wire({"a": 1})
    assert w._pages is None and w._subscribers is None

    first, second = _Reader(), _Reader()
    w._add_page(first)
    w._add_page(first)
    assert isinstance(w._pages, ReferenceType)

    w._add_page(second)
    assert isinstance(w._pages, WeakSet)

    w["a"] = 2
    assert first.invals and second.invals


def test_rows_read_by_one_region_share_one_region_set(tmp_path) -> None:
    from pywire.runtime.loader import PageLoader
    from unittest.mock import MagicMock
    import asyncio

    (tmp_path / "page.wire").write_text(
        "---\nrows = wire([{'n': i} for i in range(50)])\n---\n"
        "<ul>{$for row in rows}<li>{row['n']}</li>{/for}</ul>\n"
    )
    page = PageLoader().load(tmp_path / "page.wire")(MagicMock(), {}, {}, {}, None)
    asyncio.run(page.render(init=True))

    row_sets = [
        regions
        for (wire_obj, _field), regions in page._wire_subscribers.items()
        if wire_obj is not page.rows
    ]
    assert len(row_sets) == 50
    assert len({id(s) for s in row_sets}) == 1
