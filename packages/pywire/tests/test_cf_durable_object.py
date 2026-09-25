import time

from pywire.runtime.cf_durable_object import ThrottledPersister


def test_throttled_persister():
    base = time.monotonic()
    p = ThrottledPersister(interval=2.0)
    assert p.should_persist(base) is True  # first write always persists
    assert p.should_persist(base + 0.5) is False
    assert p.should_persist(base + 1.9) is False
    assert p.should_persist(base + 2.1) is True  # interval elapsed
    assert p.should_persist(base + 2.2) is False
    assert p.force() is True  # close/hibernate path
    now = time.monotonic()
    assert p.should_persist(now + 1.9) is False  # force reset the clock (no 2s elapsed)
    assert p.should_persist(now + 2.1) is True  # interval elapsed after force
