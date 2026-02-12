
import pytest
from pywire.core.wire import wire
from pywire.core.signals import effect

def test_wire_primitive_builtins():
    # Truthiness
    val = wire(True)
    runs = 0
    @effect
    def _():
        nonlocal runs
        runs += 1
        _ = bool(val)
    
    assert runs == 1
    val.value = False
    assert runs == 2

    # String representation
    s = wire("hello")
    assert str(s) == "hello"
    
    # Comparisons
    count = wire(10)
    runs = 0
    @effect
    def _():
        nonlocal runs
        runs += 1
        _ = count > 5
    
    assert runs == 1
    count.value = 3
    assert runs == 2
    
    assert (count < 5) is True
    assert (count <= 3) is True
    assert (count >= 3) is True
    assert (count == 3) is True
    assert (count != 4) is True

def test_wire_list_builtins():
    items = wire([1, 2, 3])
    runs = 0
    
    @effect
    def _():
        nonlocal runs
        runs += 1
        # Test __bool__ and __len__ reactivity
        if items:
            _ = len(items)
            
    assert runs == 1
    
    items.clear()
    assert runs == 2
    
    items.append(1)
    assert runs == 3

    # Comparisons
    l1 = wire([1, 2])
    assert l1 == [1, 2]
    assert l1 != [1, 2, 3]
    assert l1 < [1, 3]
    
    l2 = wire([1, 2])
    assert l1 is not l2
    # list.__eq__ doesn't know about WireList specifically, but it uses iterators
    # so l1 == l2 should work via element-wise comparison if they contain same values.
    assert l1 == l2

def test_wire_dict_builtins():
    d = wire({"a": 1})
    runs = 0
    
    @effect
    def _():
        nonlocal runs
        runs += 1
        if d:
            _ = len(d)
            
    assert runs == 1
    d.clear()
    assert runs == 2
    
    d["b"] = 2
    assert runs == 3
    
    assert d != {"a": 1}

def test_wire_set_builtins():
    s = wire({1, 2})
    runs = 0
    
    @effect
    def _():
        nonlocal runs
        runs += 1
        if s:
            _ = len(s)
            
    assert runs == 1
    s.clear()
    assert runs == 2
    
    s.add(1)
    assert runs == 3
    
    s.add(2)
    assert s > {1} # proper superset
    assert s < {1, 2, 3} # proper subset

def test_wire_primitive_format():
    price = wire(19.99)
    assert f"Price: {price:.1f}" == "Price: 20.0"
