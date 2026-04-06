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

## The `$` Syntax Sugar

To make your Python logic cleaner and more concise, `.wire` files support a special preprocessor syntax: the `$` prefix.

When you use `$` before a variable name inside the Python block of a `.wire` file, it automatically compiles to `.value`.

```python
# Your code in .wire file
def increment():
    $count += 1
    print(f"New count is {$count}")

# Compiled code
def increment(self):
    self.count.value += 1
    print(f"New count is {self.count.value}")
```

> [!TIP]
> Use `$` for read/write operations inside your functions to keep your logic readable.

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
