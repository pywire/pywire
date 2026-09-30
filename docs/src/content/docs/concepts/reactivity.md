---
title: Reactivity & State
description: Managing state with the wire primitive.
---

PyWire uses an explicit, opt-in reactivity model. Standard Python variables behave normally, while variables wrapped in `wire()` become reactive data sources that drive UI updates.

## The `wire()` Primitive

To create reactive state, initialize a variable with `wire()`.

```python
from pywire import wire

# Reactive integer
count = wire(0)

# Reactive string
username = wire("Guest")

# Reactive namespace (dictionary-like)
user = wire(name="Alice", age=30, role="admin")
```

### Reading Values

You access the underlying value using the `.value` property.

```python
print(count.value)
# Output: 0

print(user.name)
# Output: "Alice"
```

### Writing Values

Modifying the `.value` triggers the reactivity system. PyWire detects the change and marks any part of the template dependent on this variable as "dirty," queuing it for an update.

```python
count.value = 5  # Triggers UI update
user.age = 31    # Triggers UI update
```

## Automatic Unwrapping

PyWire wires are designed to feel like standard Python variables. In most cases, you don't need to manually access `.value` because wires **automatically unwrap** when used in common operations:

- **Interpolation**: `{count}` in a template works directly.
- **Comparisons**: `if count > 10:` or `$if={count > 10}`.
- **Iteration**: `for item in items:` or `$for={item in items}`.
- **Standard Ops**: `len(items)`, `str(name)`, `bool(is_active)`.
- **List/Dict Access**: `items[0]` or `user['name']`.

### When to use `.value` (or `.val`)

You only need to use the `.value` accessor in two specific scenarios:

1. **Reassignment**: When replacing the entire value of a wire.
2. **Primitive Mutation**: When using in-place operators on primitives (int, str, float).

```python
count = wire(0)

def reset():
    count.value = 0  # Reassignment requires .value

def increment():
    count.value += 1 # In-place mutation of primitive requires .value
```

> [!TIP]
> Discourage unnecessary `.value` wrapping in your templates and logic to keep your code clean and reduce potential bugs.

## Derived State

Often, you have state that depends entirely on other state. PyWire provides `derived` to handle this efficiently. Derived values are **lazily evaluated** — they only recompute when accessed after a dependency has changed. Results are memoized until a dependency updates.

### As a Decorator (`@derived`)

Use the `@derived` decorator for complex logic. The function name becomes the reactive variable.

```python
from pywire import wire, derived

count = wire(1)

@derived
def double_count():
    # Automatic unwrapping works here too!
    return count * 2

# Usage
print(double_count) # 2
count.value = 5
print(double_count) # 10
```

### As a Lambda

For simple expressions, you can pass a lambda to `derived()`.

```python
count = wire(1)
is_even = derived(lambda: count % 2 == 0)
```

### Filtering and Transforming Data

Derived values are especially useful for computed views of data:

```python
todos = wire([
    {"text": "Buy milk", "done": False},
    {"text": "Write docs", "done": True},
    {"text": "Fix bug", "done": False},
])

@derived
def pending_todos():
    return [t for t in todos if not t["done"]]

@derived
def pending_count():
    return len(pending_todos)
```

In your template, `{pending_count}` updates automatically whenever `todos` changes.

### Dependency Tracking

PyWire tracks which reactive variables are accessed during a derived function's execution. If you access `count` and `multiplier`, the derived value recomputes when either changes. You don't need to declare dependencies explicitly — just access the variables you need.

> [!NOTE]
> Circular dependencies (derived A depends on derived B, which depends on derived A) are detected at runtime and raise a `CircularDependencyError`.

## Side Effects (`@effect`)

If you need to run code _in response_ to state changes (like logging, saving to a database, or triggering external API calls), use the `@effect` decorator.

```python
from pywire import wire, effect

count = wire(0)

@effect
def log_changes():
    # This runs immediately, and then again whenever count changes
    print(f"Count changed to: {count}")
```

PyWire automatically tracks dependencies inside the effect function. If you access a reactive variable, the effect re-runs when that variable updates.

### Common Use Cases

- **Logging and analytics**: Track state changes for debugging or metrics.
- **External API calls**: Sync state to an external service when it changes.
- **Derived side effects**: Trigger actions based on computed conditions.

```python
items = wire([])

@effect
def warn_if_empty():
    if len(items) == 0:
        print("Warning: No items remaining!")
```

### When NOT to Use Effects

Don't use effects to compute derived values — use `derived` instead. Effects are for **side effects** (actions that do something beyond returning a value), not for transforming data.

## Subscribing to Changes

Both `wire()` and `@derived` support `subscribe(callback)`, which runs the callback immediately with the current value and again on every change. It returns an unsubscribe function.

```python
count = wire(0)

unsub = count.subscribe(lambda v: print(f"count is {v}"))
# Prints: count is 0  (called immediately)

count.value = 1
# Prints: count is 1

count.value = 2
# Prints: count is 2

unsub()
count.value = 3
# (no output — callback no longer subscribed)
```

`subscribe()` is sugar over `@effect` with explicit lifecycle. Use it when you have a single source and want a tidy unsubscribe handle (for example, hooking up an external listener that needs to be torn down later). Use `@effect` when you want auto-tracked dependencies across multiple wires.

```python
# Equivalent to count.subscribe(callback), but with auto-tracking:
@effect
def watch():
    callback(count.value)
```

## Scope & Persistence

### Component Scope

State defined in a `.wire` file is **scoped to the component instance**.

- If a user opens the page, a new instance of the component (and its state) is created.
- The state persists for the lifetime of that user's connection.
- If the user refreshes the page, the state resets (unless you implement external persistence like a database).

### Shared State

To share state between components or users, you should use standard Python patterns:

- **Module-level wires**: Define `wire()` objects in a separate `.py` module and import them. This is one value shared by _every_ session in the server process. When any session writes it, every page connected over WebSocket that shows it re-renders, including idle ones (long-polling and WebTransport clients see it on their next event, [#361](https://github.com/pywire/pywire/issues/361)).
- **Databases/Sessions**: For user-specific persistent data, save to a database and load it into `wire()` variables in an `@init` lifecycle hook.

```python
# src/live.py
from pywire import wire

votes = wire({"yes": 0, "no": 0})
```

```pywire
---
from live import votes

def vote(choice):
    votes[choice] += 1
---
<button @click={vote("yes")}>Yes ({votes["yes"]})</button>
<button @click={vote("no")}>No ({votes["no"]})</button>
```

#### Concurrency

Pages run on one asyncio event loop per server process, and each connection handles its events one at a time. That gives module-level wires simple rules:

- **A handler that doesn't `await` is atomic.** `votes[choice] += 1` above can't interleave with another session's handler, so no lock is needed.
- **A read-modify-write across an `await` can lose updates.** If a handler reads a shared wire, awaits (a database call, an HTTP request), then writes back, another session may have written in between. Hold an `asyncio.Lock` around the whole sequence, or re-read after the await.
- **Write from the event loop.** A `producer`'s `set_value` is safe to call from a thread. For a plain `wire()`, hop to the loop first with `loop.call_soon_threadsafe(...)`, or use an asyncio task instead of a thread.
- **Module state is per process.** With `pywire run --workers 4`, each worker has its own copy, and stateless (edge) deployments keep nothing between requests. State that must be the same for every user in production belongs in a database or Redis; use module-level wires for per-process caches, presence, and live views of data stored elsewhere.
