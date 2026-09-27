import pytest
from pywire.core.wire import wire
from pywire.core.signals import derived, effect


def test_derived_basic():
    count = wire(1)

    @derived
    def double():
        return count.value * 2

    assert double.value == 2

    count.value = 5
    assert double.value == 10


def test_derived_chaining():
    count = wire(1)

    @derived
    def double():
        return count.value * 2

    @derived
    def quadruple():
        return double.value * 2

    assert quadruple.value == 4

    count.value = 5
    assert double.value == 10
    assert quadruple.value == 20


def test_effect_basic():
    count = wire(1)
    executions = 0
    last_val = None

    @effect
    def log():
        nonlocal executions, last_val
        executions += 1
        last_val = count.value

    assert executions == 1
    assert last_val == 1

    count.value = 10
    assert executions == 2
    assert last_val == 10


def test_derived_memoization():
    count = wire(1)
    computes = 0

    @derived
    def noisy():
        nonlocal computes
        computes += 1
        return count.value

    assert computes == 0
    assert noisy.value == 1
    assert computes == 1

    # Second read should be cached
    assert noisy.value == 1
    assert computes == 1

    count.value = 2
    assert computes == 1  # still cached until read
    assert noisy.value == 2
    assert computes == 2


def test_derived_conditional_deps():
    use_a = wire(True)
    a = wire("A")
    b = wire("B")
    computes = 0

    @derived
    def result():
        nonlocal computes
        computes += 1
        if use_a.value:
            return a.value
        return b.value

    assert result.value == "A"
    assert computes == 1

    # Changing b shouldn't trigger re-compute if use_a is True
    b.value = "B2"
    assert result.value == "A"
    assert computes == 1

    # Change use_a
    use_a.value = False
    assert result.value == "B2"
    assert computes == 2

    # Now changing a shouldn't trigger re-compute
    a.value = "A2"
    assert result.value == "B2"
    assert computes == 2


def test_effect_disposal():
    count = wire(1)
    executions = 0

    def my_effect():
        nonlocal executions
        executions += 1
        _ = count.value

    eff = effect(my_effect)
    assert executions == 1

    count.value = 2
    assert executions == 2

    eff.dispose()
    count.value = 3
    assert executions == 2  # Stopped


def test_derived_template_proxy():
    count = wire(10)
    d = derived(lambda: count.value * 2)

    assert str(d) == "20"
    assert f"{d}" == "20"
    assert bool(d) is True

    count.value = 0
    assert bool(d) is False


def test_effect_batching():
    """Ensure effects don't run mid-propagation when batched."""
    from pywire.core.signals import start_batch, end_batch

    count = wire(1)
    runs = 0

    @effect
    def _():
        nonlocal runs
        runs += 1
        _ = count.value

    assert runs == 1

    start_batch()
    count.value = 2
    assert runs == 1  # Should not have run yet!
    count.value = 3
    assert runs == 1
    end_batch()

    assert runs == 2  # Should run once after batch ends


def test_cascading_writes_in_effect():
    """Ensure writes inside effects don't cause infinite loops or inconsistent states."""
    a = wire(1)
    b = wire(0)

    @effect
    def sync_b():
        b.value = a.value * 2

    assert b.value == 2

    a.value = 5
    assert b.value == 10


def test_circular_derived_raises():
    """Circular derived deps should raise CircularDependencyError, not RecursionError."""
    from pywire.core.signals import CircularDependencyError

    # Needs to be a bit careful with how we define them to ensure they are both in scope
    b_derived = None

    def get_b():
        return b_derived.value + 1

    a_derived = derived(get_b)
    b_derived = derived(lambda: a_derived.value + 1)

    with pytest.raises(CircularDependencyError):
        _ = a_derived.value


def test_write_in_derived_raises():
    """Writing to a wire inside a derived should raise ReactivityError."""
    from pywire.core.signals import ReactivityError

    counter = wire(0)

    @derived
    def bad():
        counter.value += 1
        return counter.value

    with pytest.raises(ReactivityError):
        _ = bad.value


def test_derived_unwraps_like_wire():
    # Regression for #293: Derived only proxied str/format/bool, so the docs'
    # own `len(pending_todos)` raised and `==` was silently False.
    todos = wire([{"done": False}, {"done": True}, {"done": False}])

    @derived
    def pending():
        return [t for t in todos.value if not t["done"]]

    @derived
    def total():
        return len(todos.value)

    assert len(pending) == 2
    assert [t["done"] for t in pending] == [False, False]
    assert pending[0] == {"done": False}
    assert {"done": False} in pending
    assert total == 3
    assert total != 4
    assert total > 2 and total >= 3 and total < 4 and total <= 3
    assert total + 1 == 4 and 1 + total == 4
    assert total - 1 == 2 and 10 - total == 7
    assert total * 2 == 6 and 2 * total == 6
    assert total / 2 == 1.5 and 6 / total == 2
    assert total // 2 == 1 and 7 // total == 2
    assert total % 2 == 1 and 7 % total == 1
    assert -total == -3
    assert int(total) == 3 and float(total) == 3.0


def test_derived_identity_semantics_for_reactive_nodes():
    count = wire(1)

    @derived
    def a():
        return count.value

    @derived
    def b():
        return count.value

    # Two deriveds with equal values are still distinct nodes, so sets of
    # dependencies/subscribers keep both.
    assert a == 1 and b == 1
    assert a != b
    assert len({a, b}) == 2
    assert a != count


def test_nested_container_mutation_persists():
    # Found in the bug sweep: WireList/WireDict built a proxy for a nested
    # container, but `self[i] = proxy` compared equal and skipped the store,
    # so `rows[1]["done"] = True` mutated a throwaway copy.
    rows = wire([{"done": False}, {"done": False}])
    rows[1]["done"] = True
    assert rows[1]["done"] is True

    tree = wire({"a": {"n": 1}, "tags": [1]})
    tree["a"]["n"] = 2
    tree["tags"].append(2)
    assert tree["a"]["n"] == 2
    assert tree["tags"] == [1, 2]


def test_container_wire_str_is_plain():
    # str() of a container wire recursed forever (value returns self).
    rows = wire([{"done": False}])
    rows[0]["done"] = True
    assert str(rows) == "[{'done': True}]"
    assert str(wire({"a": [1]})) == "{'a': [1]}"
    assert str(wire({1})) == "{1}"
