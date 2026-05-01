---
title: The .wire File
description: Understanding the PyWire component file format.
---

PyWire components are defined in `.wire` files. These files combine optional Python logic and mandatory HTML templates in a single file using a clean, fence-based structure.

## Structure

A `.wire` file is composed of three potential sections:

1. **Directives** (Optional): Metadata like `!path` or `!layout` at the very top.
2. **Python Block** (Optional): Python code for state and logic, wrapped in `---` fences.
3. **Template** (Mandatory): The HTML template.

```pywire
# Optional Directives
!path "/hello"

# Optional Python Block (Fenced)
---
name = wire("World")
---

<!-- HTML Template -->
<h1>Hello, {name}</h1>
```

If you don't need any Python logic, you can omit the fences:

```pywire
!path "/static"

<h1>Just HTML here</h1>
```

## Compilation

When you run your app, PyWire compiles these files into standard Python classes. This means you get full IDE support for the Python block, and the framework can optimize the rendering process.

The HTML block supports:

- **Interpolation**: `{variable.value}`
- **Attributes**: `attr={value}` or `{attr}`
- **Events**: `@click={handler}`
- **Control Flow**: `$if`, `$for`

## Page Directives

Directives are line-level metadata declared above the Python block. They configure how the page is routed, rendered, or wired up at runtime.

| Directive         | Purpose                                                                              |
| ----------------- | ------------------------------------------------------------------------------------ |
| `!path "..."`     | Sets the URL pattern this page handles.                                              |
| `!layout "..."`   | Wraps the page in a parent layout.                                                   |
| `!auth ...`       | Gates the page on an auth policy.                                                    |
| `!no_spa`         | Opts the page out of SPA navigation; renders as a full-page reload.                  |
| `!no_interactive` | Renders the page as static HTML — skips event handlers and ref wiring on the client. |

### `!no_interactive`

Mark a page as fully static for the client: no event handlers wire up, no refs, no per-handler dispatch. The WebSocket **stays connected** (so SPA navigation back to an interactive page resumes seamlessly without reconnecting), but the page itself behaves as plain HTML.

Use it for pages that don't need interactivity — marketing pages, docs, error pages — to avoid paying for client-side bookkeeping.

```pywire
!path "/about"
!no_interactive

<h1>About PyWire</h1>
<p>Server-rendered. No JS handlers attached.</p>
```

`@click`, `@input`, etc. still parse, but the client ignores them on this page. Forms continue to work via standard HTTP submit (PyWire's form-submit interception is bypassed).
