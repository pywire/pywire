---
title: Producers
description: Wrap external data sources as reactive values.
---

A `producer()` exposes an external, push-driven data source — a timer, WebSocket, polling API, file watch, or message queue — as a reactive value with the same shape as [`wire()`](/docs/concepts/reactivity).

If you only need reactive state controlled by your own code, [`wire()`](/docs/concepts/reactivity) is enough. Reach for `producer()` when the value is driven from outside your render path and you want lazy startup and explicit teardown.

## `producer(initial, start_fn)`

```python
from pywire import producer

def start(set_value):
    """Called the first time the producer is read or subscribed to."""
    import threading, time

    def tick():
        while True:
            set_value(time.time())
            time.sleep(1)

    t = threading.Thread(target=tick, daemon=True)
    t.start()

    def stop():
        pass  # cleanup if needed

    return stop

clock = producer(0, start)
```

The `start_fn` receives a `set_value(val)` callback to push new values, and may optionally return a cleanup function called when `clock.dispose()` runs.

### Lazy start

`start_fn` does not run at construction — it runs the first time anything reads `clock.value` or calls `clock.subscribe(...)`. This means a module-level `producer` doesn't spend resources until something actually needs the value.

```python
clock = producer(0, start)        # no thread yet
print(clock.value)                # start_fn fires; thread is now running
```

### Subsequent reads do not restart

Once started, `start_fn` does not run again until `dispose()` is called.

```python
clock.dispose()                   # cleanup fn runs; producer is now idle
print(clock.value)                # start_fn fires again — fresh start
```

### Without a start function

```python
constant = producer(42)           # never changes
```

Useful when you want the producer interface for a value that happens to be static.

## Reading a producer

Producers participate in the same render-context tracking as `wire()`, so reading `producer.value` inside a `.wire` template makes the region re-render whenever the producer pushes a new value.

```pywire
---
from pywire import producer
import time, threading

def start(set_value):
    def tick():
        while True:
            time.sleep(1)
            set_value(time.strftime("%H:%M:%S"))
    threading.Thread(target=tick, daemon=True).start()

now = producer("--:--:--", start)
---
<p>The time is <strong>{now.value}</strong></p>
```

## Subscribing to changes

`producer.subscribe(callback)` runs the callback immediately with the current value, then again on every push. It returns an unsubscribe function.

```python
seen = []
unsub = clock.subscribe(lambda v: seen.append(v))
# seen == [<current value>]

# After the producer pushes a new value:
# seen == [<current value>, <new value>, ...]

unsub()
# Future pushes no longer reach this callback.
```

`subscribe()` is shared with `wire()` and `derived` — see [Reactivity & State](/docs/concepts/reactivity#subscribing-to-changes).

## Sharing across pages

Like every reactive primitive, a module-level `producer` is shared across all pages and components that import it. The producer starts on the first read from any page, and continues pushing until `dispose()` is called or the process exits.

**`src/state.py`:**

```python
from pywire import producer
import threading, time

def _tick(set_value):
    def loop():
        n = 0
        while True:
            n += 1
            set_value(n)
            time.sleep(1)
    threading.Thread(target=loop, daemon=True).start()

ticks = producer(0, _tick)
```

**`src/pages/index.wire`:**

```pywire
---
from state import ticks
---
<p>Ticks: {ticks.value}</p>
```

**`src/pages/about.wire`:**

```pywire
---
from state import ticks
---
<p>Same counter on this page: {ticks.value}</p>
```

Both pages render live updates from the shared producer.

## Composing with derived

Producers participate in dependency tracking, so they can be sources for `@derived`:

```python
from pywire import producer, wire, derived

clock_value = producer(0, start_clock)
offset = wire(0)

@derived
def display():
    return clock_value.value + offset
```

`display` updates whenever the producer pushes a new value or `offset` is reassigned.

## Disposing a producer

```python
clock.dispose()
```

Calls the cleanup function returned by `start_fn` (if any) and resets the producer to its idle state. Reading `clock.value` afterwards re-runs `start_fn`. Disposal is idempotent — calling it twice is safe.
