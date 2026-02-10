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
    assert computes == 1 # still cached until read
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
    assert executions == 2 # Stopped

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
