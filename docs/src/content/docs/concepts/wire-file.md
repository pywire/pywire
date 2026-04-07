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
