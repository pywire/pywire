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

---

### `props`

Accesses properties passed to a component from its parent.

```py
@props
class Props:
    name: str
    count: int = 0
```

**Description:** Used to define a schema for incoming properties. Decorated classes are automatically instantiated and exposed to the template as the `props` object.

---

### `derived`

Creates reactive state that depends on other reactive variables.

```py
@derived
def my_computed(): ...

# or
my_computed = derived(lambda: ...)
```

**Description:** Automatically tracks reactive dependencies accessed within its function body. When any dependency changes, the derived value is recalculated lazily (only when accessed). Results are memoized until a dependency changes.

---

### `effect`

Runs side effects in response to reactive state changes.

```py
@effect
def my_effect(): ...
```

**Description:** Re-runs whenever any reactive dependency accessed within the function body updates. Ideal for logging, analytics, or manual DOM interactions via `ref`.

---

### `expose`

Marks a component method or property as accessible via `$ref` from a parent component.

```py
@expose
def open(): ...

@expose
@property
def value(): ...
```

**Description:** When a parent binds a ref to a child component using `$ref`, only methods and properties decorated with `@expose` are accessible on the ref. This provides a controlled public API for component interaction.

**Usage:**

```pywire
<!-- components/modal.wire -->
---
from pywire import wire, expose

visible = wire(False)

@expose
def open():
    visible.value = True

@expose
def close():
    visible.value = False
---
<div $if={visible} class="modal">
    {$render children}
</div>
```

```pywire
<!-- pages/index.wire -->
---
from pywire import ref
from components.modal import Modal

modal_ref = ref()
---
<button @click={modal_ref.open()}>Open Modal</button>
<Modal $ref={modal_ref}>
    <p>Modal content!</p>
</Modal>
```

---

### `ref`

Creates a reference to a DOM element or child component instance.

```py
from pywire import ref

my_ref = ref()
```

**Description:** Refs provide a way to interact with DOM elements or child components imperatively from Python. Bind a ref using the `$ref` attribute.

**Element Methods** (available when bound to an HTML element):

| Method                       | Description                      |
| ---------------------------- | -------------------------------- |
| `focus()`                    | Focus the element                |
| `blur()`                     | Remove focus from the element    |
| `scroll_to(**kwargs)`        | Scroll the element into view     |
| `add_class(name)`            | Add a CSS class                  |
| `remove_class(name)`         | Remove a CSS class               |
| `toggle_class(name)`         | Toggle a CSS class               |
| `set_attribute(name, value)` | Set an HTML attribute            |
| `remove_attribute(name)`     | Remove an HTML attribute         |
| `request_rect()`             | Request the bounding client rect |

**Properties:**

- **`.rect`** — The last known bounding client rect (after calling `request_rect()`).
- **`.value`** — The current value (for input elements).

**Usage:**

```pywire
---
from pywire import ref

input_ref = ref()

def focus_input():
    input_ref.focus()
---
<input $ref={input_ref} type="text" />
<button @click={focus_input}>Focus Input</button>
```

---

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
    static_route: str | None = None,
    static_dir: str = "static",
    max_upload_size: int = 10_485_760,
    upload_store: FileStore | None = None,
    upload_token_ttl_seconds: int = 600,
    event_defaults: Mapping[str, str] | None = None,
    secret_key: str | None = None,
    enable_webtransport: bool = False,
)
```

**Description:** Initializes the PyWire runtime, setting up the router, compiler, and WebSocket server. It conforms to the ASGI specification.

**Parameters:**

- **`pages_dir`** (`str`): Path to the directory containing your `.wire` files relative to the application root. Defaults to `"pages"`.

- **`path_based_routing`** (`bool`): If `True`, automatically generates routes based on the file structure in `pages_dir`. Defaults to `True`.

- **`enable_pjax`** (`bool`): If `True`, intercepts internal link clicks to perform soft navigations (HTML replacement) instead of full page reloads. Defaults to `True`.

- **`debug`** (`bool`): Enables developer tools, including the TUI dashboard, source maps, and detailed error overlays. Defaults to `False`.

- **`static_route`** (`str | None`): The URL prefix for serving static files. Defaults to `"/static"` when `None`. Set to `""` to serve from root (warns about page route conflicts).

- **`static_dir`** (`str`): The directory containing static assets relative to the project root. Defaults to `"static"`.

- **`max_upload_size`** (`int`): Maximum file upload size in bytes. Defaults to 10 MB.

- **`upload_store`** (`FileStore | None`): Where uploaded files wait for a form handler (for an hour at most). Defaults to a folder in the system temp directory. Processes that serve the same app must share one, such as an `ObjectStore`. See [File uploads](/docs/guides/forms/#where-files-are-kept).

- **`upload_token_ttl_seconds`** (`int`): How long an upload token remains valid. Defaults to 600 seconds.

- **`event_defaults`** (`Mapping[str, str] | None`): Per-event timing that replaces the built-in defaults, e.g. `{"input": "debounce.400ms", "scroll": "throttle.50ms"}`. See [Default timing](/docs/syntax/event-modifiers/#default-timing).

- **`secret_key`** (`str | None`): Signs state the browser carries back: stateless-mode snapshots and [multi-step form](/docs/guides/forms/#multi-step-forms) steps. Falls back to the `PYWIRE_SECRET_KEY` environment variable. Required with `stateless=True`; otherwise a random key is made per process, so processes behind a load balancer must share one.

**Extensible Hooks:**

- **`on_ws_connect(websocket) -> bool`**: Override to implement custom authentication on WebSocket connections. Return `False` to reject the connection.
- **`get_user(request_or_websocket)`**: Override to populate the `user` object available in pages from your auth system.

**Example:**

```py
from pywire import PyWire

app = PyWire(pages_dir="src/pages", debug=True)
```

## Lifecycle Hooks

---

Lifecycle hooks are functions in the frontmatter marked with a decorator. The decorators are available in every `.wire` file without an import. Hooks can be `def` or `async def`.

| Decorator        | Runs                                                                                   |
| ---------------- | -------------------------------------------------------------------------------------- |
| `@before_load`   | Pages only. Once per page load, before any `@init` hook and before the first render.   |
| `@init`          | Once per page load, before the first render. The place to fetch data.                  |
| `@mount`         | After the first render has been delivered to the browser.                              |
| `@before_update` | Before each re-render. Return `False` to skip that update (the handler still ran).     |
| `@after_update`  | After each re-render has been sent to the browser.                                     |
| `@unmount`       | When a component is removed from the render tree, or a page closes or navigates away.  |
| `@error`         | When a handler or render raises. Receives the exception; return `True` to suppress it. |

Top-level frontmatter statements run once, when the page instance is created, before any hook.

```pywire
---
# pages/users/[id].wire
user = wire({})

@init
async def load_user():
    user.value = await db.get_user(params.id)

@before_update
def only_when_loaded():
    return bool(user.value)

@error
def handle_error(exc):
    print(f"user page failed: {exc}")
    return False  # don't suppress: the error page renders
---
<h1>{user.value.get("name", "Unknown user")}</h1>
```

## Page Context Properties

---

These properties are available on every page and component instance, accessible in the Python block.

| Property   | Type              | Description                                                                                                         |
| ---------- | ----------------- | ------------------------------------------------------------------------------------------------------------------- |
| `params`   | `DotDict`         | URL parameters from the route (e.g., `params.id` for `/users/[id].wire`)                                            |
| `query`    | `DotDict`         | Query string parameters (e.g., `query.search` for `?search=foo`)                                                    |
| `path`     | `DotDict`         | Route path flags for multi-route components using `!path` dictionaries                                              |
| `url`      | `URLHelper`       | URL helper for the current request                                                                                  |
| `user`     | `Any`             | User object populated by the `get_user` hook                                                                        |
| `attrs`    | `dict`            | Fallthrough attributes not captured by `@props`                                                                     |
| `loading`  | `dict`            | Loading state for async operations                                                                                  |
| `children` | `Snippet \| None` | Implicit snippet holding the markup a parent wrote between this component's tags. Render with `{$render children}`. |

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

- **`.formData`** (`dict`): A dictionary of form fields for `@submit` events on forms. A submit event also reads like that dictionary: `event["name"]`, `event.get("name")`. See [Forms & Validation](/docs/guides/forms/).

**Mouse event properties:** `.client_x`, `.client_y`, `.offset_x`, `.offset_y`, `.page_x`, `.page_y`, `.button`.

**Modifier keys:** `.alt_key`, `.ctrl_key`, `.meta_key`, `.shift_key`.

**Example:**

```pywire
<!-- Accessing input value -->
<input @input={update_text(event.value)} />

<!-- Accessing specific key press -->
<input @keydown={handle_key(event.key)} />

<!-- Debugging event data -->
<button @click={print(event.id, event.type)}>Debug</button>
```
