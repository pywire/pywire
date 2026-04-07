---
title: Context & Injection
description: Sharing data between components without prop drilling.
---

PyWire provides a context system for passing data from parent components to deeply nested children without threading props through every intermediate component. This is useful for theming, authentication state, shared services, and other cross-cutting concerns.

## `!provide` — Making Data Available

The `!provide` directive makes values available to all child components rendered within the current page or component.

```pywire
<!-- pages/index.wire -->
!provide { 'THEME': theme, 'USER': current_user }

---
theme = wire("dark")
current_user = wire(name="Alice", role="admin")
---
<div>
    <Sidebar />
    <MainContent />
</div>
```

The syntax is a dictionary mapping string keys to expressions:

```
!provide { 'KEY_NAME': expression, 'ANOTHER_KEY': another_expression }
```

## `!inject` — Consuming Provided Data

Child components use the `!inject` directive to pull values from the nearest ancestor that provides them.

```pywire
<!-- components/sidebar.wire -->
!inject { theme: 'THEME', user: 'USER' }

<nav class={f"sidebar sidebar-{theme}"}>
    <p>Welcome, {user.name}</p>
</nav>
```

The syntax maps local variable names to the context keys:

```
!inject { local_variable: 'KEY_NAME' }
```

After injection, `theme` and `user` are available as regular variables in both the Python block and the template.

## Example: Theming

A common use case is providing a theme to an entire component tree.

**Layout (provides the theme):**

```pywire
<!-- pages/__layout__.wire -->
!provide { 'THEME': theme_color }

---
theme_color = wire("light")

def toggle_theme():
    if theme_color.value == "light":
        theme_color.value = "dark"
    else:
        theme_color.value = "light"
---
<div class={f"app theme-{theme_color}"}>
    <button @click={toggle_theme}>Toggle Theme</button>
    <slot />
</div>
```

**Any nested component (consumes the theme):**

```pywire
<!-- components/card.wire -->
!inject { theme: 'THEME' }

<div class={f"card card-{theme}"}>
    <slot />
</div>

<style scoped>
    .card-light { background: white; color: black; }
    .card-dark { background: #1e293b; color: white; }
</style>
```

## Programmatic Context API

In addition to the template directives, you can manage context from Python code using `set_context()` and `get_context()` on any page or component instance.

### `self.set_context(key, value)`

Sets a context value that child components can access:

```python
def on_before_load(self):
    user = get_user_from_session(self.request)
    self.set_context("CURRENT_USER", user)
```

### `self.get_context(key, default=None)`

Reads a context value set by an ancestor:

```python
def on_load(self):
    user = self.get_context("CURRENT_USER")
    if user:
        self.greeting = f"Welcome, {user.name}"
```

### When to Use Each Approach

| Approach                          | Best for                                                                                |
| --------------------------------- | --------------------------------------------------------------------------------------- |
| `!provide` / `!inject`            | Static context known at template compile time                                           |
| `set_context()` / `get_context()` | Dynamic context set based on runtime conditions (request state, database lookups, auth) |

Both approaches share the same underlying context dictionary, so values set with `set_context()` are accessible via `!inject` and vice versa.

## Key Points

- Context keys are strings — use descriptive, uppercase names by convention (e.g., `'THEME'`, `'AUTH_USER'`).
- Injected values are reactive — if the provided wire changes, all injecting components update automatically.
- If a key is not found in any ancestor, the injected variable will be `None`.
- Context is resolved at render time from the nearest providing ancestor.
