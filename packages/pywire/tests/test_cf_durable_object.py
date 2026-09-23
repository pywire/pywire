from pywire.runtime.cf_durable_object import ThrottledPersister

def test_throttled_persister():
    p = ThrottledPersister(interval=2.0)
    assert p.should_persist(100.0) is True     # first write always persists
    assert p.should_persist(100.5) is False
    assert p.should_persist(101.9) is False
    assert p.should_persist(102.1) is True     # interval elapsed
    assert p.should_persist(102.2) is False
    assert p.force() is True                   # close/hibernate path
    assert p.should_persist(102.3) is False    # force reset the clock