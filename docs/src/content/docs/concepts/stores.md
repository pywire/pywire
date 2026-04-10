---
title: Stores
description: Subscription-based reactive stores for shared and external state.
---

Stores provide a subscription-based API on top of the [wire reactivity system](/docs/concepts/reactivity). They are useful for state that needs explicit subscription management, producer/consumer patterns, or sharing reactive values across components.

If you just need reactive state within a single component, [`wire()`](/docs/concepts/reactivity) is simpler and sufficient. Stores add value when you need:

- **Subscription callbacks** — run code when a value changes
- **External data sources** — wrap a timer, WebSocket, or API poll as a reactive value
- **Derived aggregations** — combine multiple stores into a computed value

## `writable(initial)`

Creates a read/write store.

```python
from pywire import writable

count = writable(0)

# Read
print(count.value)  # 0

# Write
count.value = 5
count.set(10)
count.update(lambda n: n + 1)  # 11
```

### Subscribing to Changes

`subscribe()` takes a callback that is called immediately with the current value and again on every subsequent change. It returns an unsubscribe function.

```python
values = []
unsub = count.subscribe(lambda v: values.append(v))
# values == [11]  (called immediately)

count.value = 20
# values == [11, 20]

unsub()
count.value = 30
# values == [11, 20]  (no longer subscribed)
```

## `readable(initial, start_fn)`

Creates a read-only store. There is no `.set()` or `.value` setter — the value is controlled by the `start_fn` producer function.

```python
from pywire import readable

def start(set_value):
    """Called when the first subscriber appears."""
    import threading

    def tick():
        import time
        while True:
            set_value(time.time())
            time.sleep(1)

    t = threading.Thread(target=tick, daemon=True)
    t.start()

    def stop():
        pass  # cleanup if needed

    return stop

clock = readable(0, start)
```

The `start_fn` receives a `set_value` callback and optionally returns a `stop` function. The producer starts lazily — only when the first subscriber appears — and stops when the last subscriber unsubscribes.

```python
unsub = clock.subscribe(lambda t: print(f"Time: {t}"))
# Producer starts, prints time every second

unsub()
# Producer stops (stop function called)
```

Without a `start_fn`, `readable()` creates a store whose value never changes — useful for constants you want to expose through the store interface.

## `store_derived(stores, fn)`

Creates a derived store from one or more source stores. The value recomputes automatically when any source changes.

```python
from pywire import writable, store_derived

width = writable(10)
height = writable(20)

area = store_derived([width, height], lambda w, h: w * h)
print(area.value)  # 200

width.value = 15
print(area.value)  # 300
```

For a single source store, you can pass it directly instead of a list:

```python
count = writable(5)
doubled = store_derived(count, lambda n: n * 2)
print(doubled.value)  # 10
```

Derived stores support `subscribe()` just like writable and readable stores:

```python
doubled.subscribe(lambda v: print(f"Doubled: {v}"))
```

## Sharing State Across Pages

The primary use case for stores is sharing reactive state across multiple pages. Define your stores in a separate module and import them into each page's Python block.

**`src/stores.py`:**

```python
from pywire import writable, store_derived

counter = writable(0)
counter_label = store_derived(counter, lambda n: f"Count: {n} ({'even' if n % 2 == 0 else 'odd'})")
```

**`src/pages/index.wire`:**

```pywire
---
from stores import counter, counter_label

def increment():
    counter.value += 1

def decrement():
    counter.value -= 1

def reset():
    counter.set(0)
---
<p><strong>{counter_label.value}</strong></p>
<button @click={decrement()}>−</button>
<button @click={increment()}>+</button>
<button @click={reset()}>Reset</button>
```

**`src/pages/about.wire`:**

```pywire
---
from stores import counter

def increment():
    counter.value += 1
---
<p>The counter value here is live: <strong>{counter.value}</strong></p>
<button @click={increment()}>Increment from About</button>
```

The store lives at the module level, so both pages share the same value. Incrementing from either page updates both — including live re-renders via WebSocket — and SPA navigation between pages preserves the count without a server round-trip.

## Integration with Wire Reactivity

Stores use `wire()` internally, so they participate in PyWire's render context tracking automatically. If you access `store.value` inside a `@derived` or `@effect`, the dependency is tracked:

```python
from pywire import writable, derived, effect

count = writable(0)

@derived
def display():
    return f"Count is {count.value}"

@effect
def log_changes():
    print(f"Count changed to {count.value}")
```

This means stores work seamlessly within `.wire` file templates — just reference `store.value` in your template and the region re-renders when the store changes.
