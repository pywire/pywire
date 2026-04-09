"""Tests for the Svelte-inspired store system."""

import pytest

from pywire.core.stores import writable, readable, store_derived, WritableStore, ReadableStore, DerivedStore
from pywire.core.signals import Effect, Derived, _TRACKING_STACK
from pywire.core.wire import WirePrimitive, set_render_context, reset_render_context


# ---------------------------------------------------------------------------
# WritableStore
# ---------------------------------------------------------------------------


class TestWritableStore:
    def test_create_and_read(self):
        s = writable(42)
        assert isinstance(s, WritableStore)
        assert s.value == 42

    def test_set_value(self):
        s = writable(0)
        s.value = 10
        assert s.value == 10

    def test_set_method(self):
        s = writable("hello")
        s.set("world")
        assert s.value == "world"

    def test_update_method(self):
        s = writable(5)
        s.update(lambda v: v * 2)
        assert s.value == 10

    def test_subscribe_receives_current_value(self):
        s = writable(99)
        received = []
        s.subscribe(lambda v: received.append(v))
        # Should have been called immediately with current value
        assert received == [99]

    def test_subscribe_receives_updates(self):
        s = writable(1)
        received = []
        s.subscribe(lambda v: received.append(v))
        s.value = 2
        s.set(3)
        s.update(lambda v: v + 1)
        assert received == [1, 2, 3, 4]

    def test_unsubscribe_stops_callbacks(self):
        s = writable(0)
        received = []
        unsub = s.subscribe(lambda v: received.append(v))
        assert received == [0]
        unsub()
        s.value = 1
        # Should NOT have received the update
        assert received == [0]

    def test_multiple_subscribers(self):
        s = writable(0)
        a_vals = []
        b_vals = []
        unsub_a = s.subscribe(lambda v: a_vals.append(v))
        unsub_b = s.subscribe(lambda v: b_vals.append(v))
        s.value = 1
        assert a_vals == [0, 1]
        assert b_vals == [0, 1]
        unsub_a()
        s.value = 2
        assert a_vals == [0, 1]  # stopped
        assert b_vals == [0, 1, 2]  # still going

    def test_repr(self):
        s = writable(42)
        assert "42" in repr(s)


# ---------------------------------------------------------------------------
# ReadableStore
# ---------------------------------------------------------------------------


class TestReadableStore:
    def test_create_no_start(self):
        s = readable(10)
        assert isinstance(s, ReadableStore)
        assert s.value == 10

    def test_no_setter(self):
        s = readable(10)
        with pytest.raises(AttributeError):
            s.value = 20  # type: ignore[misc]

    def test_start_fn_called_on_first_subscribe(self):
        started = []
        stopped = []

        def start(set_val):
            started.append(True)
            set_val(100)

            def stop():
                stopped.append(True)

            return stop

        s = readable(0, start)
        assert started == []  # Not yet

        received = []
        unsub = s.subscribe(lambda v: received.append(v))
        assert started == [True]
        # The start function set the value to 100, so our callback should get 100
        # (first call gets initial=0 before start runs, then start sets to 100)
        # Actually: start runs BEFORE callback is added (start is called first),
        # but the callback is added after start, so it gets 100 via the immediate call.
        # Let's check what actually happened:
        # 1. start_fn(setter) is called -> setter(100) fires, but _subscribers is empty at that point
        # 2. callback is added to _subscribers
        # 3. callback(self._wire._value) is called -> value is now 100
        assert received == [100]

    def test_stop_fn_called_on_last_unsubscribe(self):
        stopped = []

        def start(set_val):
            def stop():
                stopped.append(True)

            return stop

        s = readable(0, start)
        unsub1 = s.subscribe(lambda v: None)
        unsub2 = s.subscribe(lambda v: None)
        assert stopped == []
        unsub1()
        assert stopped == []  # Still one subscriber
        unsub2()
        assert stopped == [True]  # Last subscriber gone

    def test_start_fn_updates_propagate(self):
        setter_ref = []

        def start(set_val):
            setter_ref.append(set_val)
            return lambda: None

        s = readable(0, start)
        received = []
        s.subscribe(lambda v: received.append(v))

        # Use the captured setter to push values
        setter_ref[0](10)
        setter_ref[0](20)
        assert received == [0, 10, 20]

    def test_repr(self):
        s = readable(42)
        assert "42" in repr(s)


# ---------------------------------------------------------------------------
# DerivedStore (store_derived)
# ---------------------------------------------------------------------------


class TestDerivedStore:
    def test_derive_from_single_store(self):
        count = writable(5)
        doubled = store_derived(count, lambda v: v * 2)
        assert isinstance(doubled, DerivedStore)
        assert doubled.value == 10

    def test_derive_from_multiple_stores(self):
        a = writable(2)
        b = writable(3)
        product = store_derived([a, b], lambda x, y: x * y)
        assert product.value == 6

    def test_derived_updates_when_source_changes(self):
        count = writable(1)
        doubled = store_derived(count, lambda v: v * 2)
        assert doubled.value == 2
        count.value = 5
        assert doubled.value == 10

    def test_derived_subscribe(self):
        count = writable(1)
        doubled = store_derived(count, lambda v: v * 2)
        received = []
        unsub = doubled.subscribe(lambda v: received.append(v))
        # Effect runs immediately
        assert received == [2]
        count.value = 3
        assert received == [2, 6]
        unsub()
        count.value = 10
        assert received == [2, 6]  # No more updates

    def test_repr(self):
        s = writable(5)
        d = store_derived(s, lambda v: v + 1)
        # Force evaluation
        _ = d.value
        assert "6" in repr(d)


# ---------------------------------------------------------------------------
# Integration with Wire reactivity (render context tracking)
# ---------------------------------------------------------------------------


class TestStoreWireIntegration:
    def test_writable_tracks_in_signal_context(self):
        """Store value access inside a Derived should register as dependency."""
        s = writable(10)
        d = Derived(lambda: s.value + 1)
        assert d.value == 11
        s.value = 20
        assert d.value == 21

    def test_readable_tracks_in_signal_context(self):
        s = readable(5)
        d = Derived(lambda: s.value * 3)
        assert d.value == 15

    def test_writable_tracks_in_effect(self):
        s = writable(1)
        observed = []
        eff = Effect(lambda: observed.append(s.value))
        assert observed == [1]
        s.value = 2
        assert observed == [1, 2]
        eff.dispose()
        s.value = 3
        assert observed == [1, 2]  # disposed

    def test_writable_integrates_with_render_context(self):
        """Store value access within render context should register the page."""
        s = writable(42)

        class FakePage:
            def __init__(self):
                self.registered = []

            def _register_wire_read(self, wire_obj, field, region_id):
                self.registered.append((wire_obj, field, region_id))

        page = FakePage()
        token = set_render_context(page, "r0")
        try:
            _ = s.value
        finally:
            reset_render_context(token)

        # The internal WirePrimitive should have registered the page
        assert len(page.registered) == 1
        assert page.registered[0][1] == "value"
        assert page.registered[0][2] == "r0"


# ---------------------------------------------------------------------------
# Edge cases and error handling
# ---------------------------------------------------------------------------


class TestStoreEdgeCases:
    def test_double_unsubscribe_is_safe(self):
        """Calling unsubscribe twice should not raise."""
        s = writable(1)
        unsub = s.subscribe(lambda v: None)
        unsub()
        unsub()  # should not raise

    def test_subscriber_exception_does_not_break_others(self):
        """A subscriber that throws should not prevent other subscribers from receiving updates."""
        s = writable(0)
        good_vals = []

        def bad_sub(v):
            raise ValueError("boom")

        def good_sub(v):
            good_vals.append(v)

        s.subscribe(good_sub)
        s.subscribe(bad_sub)
        s.value = 1  # should not raise despite bad_sub
        assert good_vals == [0, 1]

    def test_subscriber_modifying_store_during_callback(self):
        """Subscriber that modifies the store during its callback (reentrancy)."""
        s = writable(0)
        vals = []

        def reentrant_sub(v):
            vals.append(v)
            if v == 1:
                s.value = 2  # reentrant write

        s.subscribe(reentrant_sub)
        s.value = 1
        # Should have received 0 (initial), 1, and 2
        assert 0 in vals
        assert 1 in vals
        assert 2 in vals

    def test_readable_start_fn_returns_non_callable(self):
        """start_fn that returns a non-callable value should not crash on unsubscribe."""

        def start(set_val):
            return "not a function"  # not callable

        s = readable(0, start)
        unsub = s.subscribe(lambda v: None)
        unsub()  # should not raise

    def test_nested_derived_stores(self):
        """Derived store from another derived store."""
        base = writable(2)
        doubled = store_derived(base, lambda v: v * 2)
        quadrupled = store_derived(doubled, lambda v: v * 2)
        assert quadrupled.value == 8
        base.value = 5
        assert quadrupled.value == 20

    def test_derived_with_multiple_stores_one_changes(self):
        """Derived from multiple stores updates when any source changes."""
        a = writable(10)
        b = writable(20)
        total = store_derived([a, b], lambda x, y: x + y)
        assert total.value == 30
        a.value = 15
        assert total.value == 35
        b.value = 25
        assert total.value == 40

    def test_readable_double_unsubscribe_does_not_double_stop(self):
        """Double unsubscribe should only call stop_fn once."""
        stop_count = []

        def start(set_val):
            return lambda: stop_count.append(True)

        s = readable(0, start)
        unsub = s.subscribe(lambda v: None)
        unsub()
        unsub()
        assert len(stop_count) == 1

class TestPublicAPI:
    def test_imports_from_pywire(self):
        from pywire import writable, readable, store_derived

        s = writable(1)
        assert s.value == 1
