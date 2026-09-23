import logging
from collections import defaultdict

from pywire import wire
from pywire.core.wire import reset_render_context, set_render_context
from pywire.runtime.page import BasePage as Page


class FakePage(Page):
    """Minimal Page: only the attrs _register_wire_read/_invalidate_wire touch."""

    def __init__(self):
        self._wire_subscribers = defaultdict(set)
        self._region_dependencies = defaultdict(set)
        self._capturing_deps = False
        self._captured_deps = set()
        self._wire_write_seq = 0
        self._dirty_regions = set()


def test_wire_debug_logs_lazy(caplog):
    w = wire(1)
    page = FakePage()
    w._pages.add(page)  # _pages is a WeakSet; keep a strong ref
    token = set_render_context(page, "r0")
    try:
        with caplog.at_level(logging.DEBUG, logger="pywire"):
            _ = w.value  # registers read (render context)
            w.value = 2
    finally:
        reset_render_context(token)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("WIRE-NOTIFY" in m for m in msgs)
    notify = [r for r in caplog.records if "WIRE-NOTIFY" in r.getMessage()][0]
    assert notify.args, "expected lazy %-args on hot-path debug log"
    reg = [r for r in caplog.records if "register_read:" in r.getMessage()][0]
    assert reg.args, "expected lazy %-args on register_read debug log"


def test_no_formatting_when_disabled(caplog):
    w = wire(1)
    with caplog.at_level(logging.INFO, logger="pywire"):
        for i in range(100):
            w.value = i
    assert not [r for r in caplog.records if "WIRE-NOTIFY" in r.getMessage()]
