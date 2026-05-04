"""Tests for `.subscribe(cb)` on wire and derived.

Subscribe is sugar over `Effect`: callback fires immediately with the
current value, again on every subsequent change, and stops on the
returned unsub closure.
"""

import pytest

from pywire import wire, derived
from pywire.core.signals import Derived
from pywire.core.wire import WireDict


class TestWireSubscribe:
    def test_callback_fires_immediately_with_current_value(self):
        w = wire(42)
        seen = []
        w.subscribe(lambda v: seen.append(v))
        assert seen == [42]

    def test_callback_fires_on_change(self):
        w = wire(0)
        seen = []
        w.subscribe(lambda v: seen.append(v))
        w.value = 1
        w.value = 2
        assert seen == [0, 1, 2]

    def test_unsubscribe_stops_callbacks(self):
        w = wire(0)
        seen = []
        unsub = w.subscribe(lambda v: seen.append(v))
        assert seen == [0]
        unsub()
        w.value = 99
        assert seen == [0]

    def test_multiple_subscribers_independent(self):
        w = wire(0)
        a, b = [], []
        unsub_a = w.subscribe(lambda v: a.append(v))
        w.subscribe(lambda v: b.append(v))
        w.value = 1
        assert a == [0, 1]
        assert b == [0, 1]
        unsub_a()
        w.value = 2
        assert a == [0, 1]
        assert b == [0, 1, 2]

    def test_double_unsubscribe_safe(self):
        w = wire(1)
        unsub = w.subscribe(lambda v: None)
        unsub()
        unsub()  # must not raise

    def test_subscribe_on_collection_wire(self):
        d = wire({"name": "Alice"})
        seen = []
        assert isinstance(d, WireDict)
        d.subscribe(lambda v: seen.append(dict(v)))
        d["name"] = "Bob"
        # Initial fire + one mutation
        assert len(seen) == 2
        assert seen[0]["name"] == "Alice"
        assert seen[1]["name"] == "Bob"


class TestDerivedSubscribe:
    def test_subscribes_to_derived_value(self):
        src = wire(2)

        @derived
        def doubled():
            return src * 2

        seen = []
        doubled.subscribe(lambda v: seen.append(v))
        assert seen == [4]
        src.value = 5
        assert seen == [4, 10]

    def test_unsubscribe_stops_derived_updates(self):
        src = wire(0)

        @derived
        def squared():
            return src * src

        seen = []
        unsub = squared.subscribe(lambda v: seen.append(v))
        src.value = 3
        unsub()
        src.value = 4
        assert seen == [0, 9]

    def test_derived_constructed_directly(self):
        """Derived created via constructor (not decorator) supports subscribe."""
        src = wire(10)
        d = Derived(lambda: src.value + 1)
        seen = []
        d.subscribe(lambda v: seen.append(v))
        src.value = 20
        assert seen == [11, 21]


class TestSubscribeReentrancy:
    def test_subscriber_can_modify_wire(self):
        w = wire(0)
        seen = []

        def cb(v):
            seen.append(v)
            if v == 1:
                w.value = 2

        w.subscribe(cb)
        w.value = 1
        # Initial 0, then 1 (which triggers reentrant write to 2), then 2
        assert 0 in seen and 1 in seen and 2 in seen

    def test_subscriber_exception_propagates_to_caller(self):
        """Effect doesn't swallow exceptions; subscriber errors should surface.

        Behavioral difference from old WritableStore.subscribe (which
        silently swallowed exceptions). With wire.subscribe being thin
        sugar over Effect, errors propagate. This is the intended
        change — silent swallowing hides bugs.
        """
        w = wire(0)

        def bad(_):
            raise ValueError("boom")

        with pytest.raises(ValueError):
            w.subscribe(bad)
