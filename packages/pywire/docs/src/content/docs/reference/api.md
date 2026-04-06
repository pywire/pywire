---
title: Core API Reference
---

This reference documents the core Python API for PyWire. It covers the essential primitives for state management, application configuration, and runtime interaction.

## Core Primitives

---

### `wire`

The fundamental building block of reactive state in PyWire.

```py
class wire(initial_value: Any, **kwargs: Any)
```

**Description:** Wraps a value to make it reactive. When the value changes, any component rendering this wire is automatically scheduled for an update.

**Arguments:**

- **`initial_value`** (`Any`): The starting value. This can be a primitive (int, str, bool), a list, a dictionary, or an object.

- **`**kwargs`** (`Any`): If provided, the wire is initialized as a **Namespace** object (similar to a dictionary or `SimpleNamespace`), where keys become reactive attributes.

**Properties:**

- **`.value`**: Accesses or modifies the underlying value. Writing to this property triggers reactivity.

**Usage:**

```py
from pywire import wire

# 1. Primitive State
count = wire(0)
print(count.value)  # Read
count.value += 1    # Write (Trigger)

# 2. Namespace State (Object-like)
user = wire(name="Alice", age=30)
print(user.name)    # Read attribute
user.age = 31       # Write attribute (Trigger)
```

**Note:** Inside a `.wire` file's Python block, you can use the `$` prefix sugar (e.g., `$count`, `$user.age`) which compiles to `.value`.

## Application Class

---

### `PyWire`

The main ASGI application entry point.

```py
class PyWire(
    pages_dir: str = "pages",
    path_based_routing: bool = True,
    enable_pjax: bool = True,
    debug: bool = False,
    static_path: str = "/static"
)
```

**Description:** Initializes the PyWire runtime, setting up the router, compiler, and WebSocket server. It conforms to the ASGI specification.

**Parameters:**

- **`pages_dir`** (`str`): Path to the directory containing your `.wire` files relative to the application root. Defaults to `"pages"`.

- **`path_based_routing`** (`bool`): If `True`, automatically generates routes based on the file structure in `pages_dir`. Defaults to `True`.

- **`enable_pjax`** (`bool`): If `True`, intercepts internal link clicks to perform soft navigations (HTML replacement) instead of full page reloads. Defaults to `True`.

- **`debug`** (`bool`): Enables developer tools, including the TUI dashboard, source maps, and detailed error overlays. Defaults to `False`.

- **`static_path`** (`str`): The URL prefix for serving static files. Defaults to `"/static"`.

**Example:**

```py
from pywire import PyWire

app = PyWire(pages_dir="src/pages", debug=True)
```

## Lifecycle Hooks

---

These functions are optional definitions you can place inside your component's script block.

### `mount`

**Description:** Runs **once** on the server when the component is first initialized for a user session. This is the ideal place to load data, check authentication, or initialize `wire` variables based on URL parameters.

**Example:**

```py
# pages/users/[id].wire
user_id = wire(None)
user_data = wire({})

@mount
def fetch_data(params):
    $user_id = params.get("id")
    # Fetch data from database synchronously or asynchronously
    $user_data = db.get_user($user_id)
```

## Runtime Helpers

---

Utility functions available in the `pywire.runtime.helpers` module to interact with the client-side environment from the server.

### `relocate`

```py
def relocate(path: str) -> None
```

**Description:** Commands the browser to navigate to a new URL. This is handled via the WebSocket connection.

**Arguments:**

- **`path`** (`str`): The destination URL (relative or absolute).

**Example:**

```py
from pywire.runtime.helpers import relocate

def login_handler():
    if verify_user():
        relocate("/dashboard")
```

## Template Context Variables

---

Special variables available strictly within the HTML template context.

### `event`

Represents the client-side DOM event payload. Available **only** inside event handler expressions (e.g., `@click={...}`).
Also available as `$event` for compatibility with other frameworks.

**Properties:**

- **`.id`** (`str`): The ID of the element that triggered the event.

- **`.type`** (`str`): The type of the event (e.g., `"click"`, `"input"`).

- **`.value`** (`Any`): The value of the element.
  - For `<input type="text">`, returns the string text.
  - For `<input type="checkbox">` or `<input type="radio">`, returns the checked state (boolean) via `event.checked`.
  - For `<select>`, returns the selected option's value.

- **`.checked`** (`bool`): The checked state for checkbox/radio inputs.

- **`.key`** (`str`): The key value for keyboard events (e.g., `"Enter"`, `"Escape"`, `"a"`).

- **`.keyCode`** (`int`): The integer key code for keyboard events.

- **`.formData`** (`dict`): A dictionary of form fields for `@submit` events on forms.

**Example:**

```html
<!-- Accessing input value -->
<input @input="{update_text(event.value)}" />

<!-- Accessing specific key press -->
<input @keydown="{handle_key(event.key)}" />

<!-- Debugging event data -->
<button @click="{print(event.id, event.type)}">Debug</button>
```
