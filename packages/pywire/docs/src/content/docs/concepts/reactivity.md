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

Often, you have state that depends entirely on other state. PyWire provides `derived` to handle this efficiently. Derived values update automatically when their dependencies change.

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

## Side Effects (`@effect`)

If you need to run code _in response_ to state changes (like logging, saving to local storage, or fetching data), use the `@effect` decorator.

```python
from pywire import wire, effect

count = wire(0)

@effect
def log_changes():
    # This runs immediately, and then again whenever count changes
    print(f"Count changed to: {count}")
```

PyWire automatically tracks dependencies inside the effect function. If you access a reactive variable, the effect re-runs when that variable updates.

## Scope & Persistence

### Component Scope

State defined in a `.wire` file is **scoped to the component instance**.

- If a user opens the page, a new instance of the component (and its state) is created.
- The state persists for the lifetime of that user's connection.
- If the user refreshes the page, the state resets (unless you implement external persistence like a database).

### Shared State

To share state between components or users, you should use standard Python patterns:

- **Global Variables**: Define `wire()` objects in a separate `.py` module and import them. This creates global, singleton state shared by _all_ users (be careful!).
- **Databases/Sessions**: For user-specific persistent data, save to a database and load it into `wire()` variables during the `mount()` lifecycle hook.
