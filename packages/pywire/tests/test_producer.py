"""Tests for the producer() primitive.

Producer wraps an external data source as a reactive value. Lazy
start (on first .value or .subscribe), manual stop (via .dispose).
"""

import threading
import time

from pywire import producer, wire, derived
from pywire.core.signals import Effect, Derived
from pywire.core.wire import set_render_context, reset_render_context


class FakePage:
    def __init__(self):
        self.registered = []
        self.invalidations = []

    def _register_wire_read(self, wire_obj, field, region_id):
        self.registered.append((wire_obj, field, region_id))

    def _invalidate_wire(self, wire_obj, field):
        self.invalidations.append((wire_obj, field))


class TestProducerLifecycle:
    def test_no_start_fn_constant_value(self):
        p = producer(42)
        assert p.value == 42

    def test_start_fn_runs_lazily_on_first_read(self):
        started = []

        def start(set_val):
            started.append(True)
            set_val(99)

        p = producer(0, start)
        assert started == []  # not started yet
        v = p.value
        assert started == [True]
        assert v == 99

    def test_start_fn_runs_lazily_on_first_subscribe(self):
        started = []

        def start(set_val):
            started.append(True)
            set_val(7)

        p = producer(0, start)
        seen = []
        p.subscribe(lambda v: seen.append(v))
        assert started == [True]
        assert seen == [7]

    def test_start_fn_runs_only_once(self):
        started = []

        def start(set_val):
            started.append(True)

        p = producer(0, start)
        _ = p.value
        _ = p.value
        p.subscribe(lambda v: None)
        assert started == [True]

    def test_dispose_runs_stop_fn(self):
        stopped = []

        def start(set_val):
            return lambda: stopped.append(True)

        p = producer(0, start)
        _ = p.value  # trigger start
        p.dispose()
        assert stopped == [True]

    def test_dispose_idempotent(self):
        stopped = []

        def start(set_val):
            return lambda: stopped.append(True)

        p = producer(0, start)
        _ = p.value
        p.dispose()
        p.dispose()
        assert stopped == [True]

    def test_dispose_then_read_restarts(self):
        starts = []

        def start(set_val):
            starts.append(True)
            set_val(1)

        p = producer(0, start)
        _ = p.value
        p.dispose()
        _ = p.value
        assert starts == [True, True]

    def test_start_fn_returning_non_callable_safe_on_dispose(self):
        def start(set_val):
            return "not a callable"

        p = producer(0, start)
        _ = p.value
        p.dispose()  # must not raise


class TestProducerReactivity:
    def test_producer_pushes_value_changes(self):
        setter_box = []

        def start(set_val):
            setter_box.append(set_val)

        p = producer(0, start)
        seen = []
        p.subscribe(lambda v: seen.append(v))
        setter_box[0](10)
        setter_box[0](20)
        assert seen == [0, 10, 20]

    def test_producer_no_op_write_does_not_fire(self):
        setter_box = []

        def start(set_val):
            setter_box.append(set_val)

        p = producer(0, start)
        seen = []
        p.subscribe(lambda v: seen.append(v))
        setter_box[0](0)  # same value
        assert seen == [0]

    def test_producer_in_derived(self):
        setter_box = []

        def start(set_val):
            setter_box.append(set_val)

        p = producer(1, start)
        d = Derived(lambda: p.value * 10)
        assert d.value == 10
        setter_box[0](5)
        assert d.value == 50

    def test_producer_in_effect(self):
        setter_box = []

        def start(set_val):
            setter_box.append(set_val)

        p = producer(0, start)
        seen = []
        eff = Effect(lambda: seen.append(p.value))
        setter_box[0](42)
        assert seen == [0, 42]
        eff.dispose()


class TestProducerCrossPage:
    """Producer must invalidate every page that read its value."""

    def test_two_pages_both_invalidated_on_producer_push(self):
        setter_box = []

        def start(set_val):
            setter_box.append(set_val)

        p = producer(0, start)
        p1, p2 = FakePage(), FakePage()

        for page in (p1, p2):
            tok = set_render_context(page, "r0")
            try:
                _ = p.value
            finally:
                reset_render_context(tok)

        setter_box[0](100)
        assert p1.invalidations and p2.invalidations
        assert p.value == 100

    def test_module_level_producer_with_concurrent_thread(self):
        """End-to-end smoke: producer pushes from a real thread, subscriber sees values."""
        seen = []

        def start(set_val):
            def push():
                for i in range(1, 4):
                    time.sleep(0.02)
                    set_val(i)

            t = threading.Thread(target=push, daemon=True)
            t.start()
            return None

        p = producer(0, start)
        unsub = p.subscribe(lambda v: seen.append(v))
        time.sleep(0.2)
        unsub()
        assert seen[0] == 0
        assert 3 in seen


class TestProducerDerivedComposition:
    def test_derived_from_producer(self):
        setter_box = []

        def start(set_val):
            setter_box.append(set_val)

        clock = producer(0, start)

        @derived
        def doubled():
            return clock.value * 2

        assert doubled.value == 0
        setter_box[0](5)
        assert doubled.value == 10

    def test_derived_combining_producer_and_wire(self):
        setter_box = []

        def start(set_val):
            setter_box.append(set_val)

        external = producer(10, start)
        local = wire(2)

        @derived
        def combined():
            return external.value + local * 5

        assert combined.value == 20
        local.value = 4
        assert combined.value == 30
        setter_box[0](100)
        assert combined.value == 120


class TestProducerPublicAPI:
    def test_imports_from_pywire(self):
        from pywire import producer, Producer  # noqa: F401

        p = producer(1)
        assert isinstance(p, Producer)
        assert p.value == 1
