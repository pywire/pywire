---
title: The .wire File
description: Understanding the PyWire component file format.
---

PyWire components are defined in `.wire` files. These files combine Python logic and HTML templates in a single file, separating them with a triple-dash (`---html---`) marker.

## Structure

A `.wire` file typically has two parts:

1. **Python Block**: (Top) Define your reactive state, imports, and event handlers.
2. **HTML Block**: (Bottom) Define the UI using standard HTML and PyWire template syntax.

```pywire
# Python Block
name = wire("World")

---html---
<!-- HTML Block -->
<h1>Hello, {name.value}</h1>
```

## Compilation

When you run your app, PyWire compiles these files into standard Python classes. This means you get full IDE support for the Python block, and the framework can optimize the rendering process.

The HTML block supports:

- **Interpolation**: `{variable.value}`
- **Attributes**: `attr={value}` or `{attr}`
- **Events**: `@click={handler}`
- **Control Flow**: `$if`, `$for`
