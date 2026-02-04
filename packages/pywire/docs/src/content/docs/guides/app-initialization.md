---
title: App Initialization
description: Configuring and starting the PyWire application.
---

Every PyWire project starts with an application instance. This is typically defined in a file named `app.py` or `main.py` in your project root.

## The `PyWire` Class

The `PyWire` class is the main entry point. It initializes the ASGI application, the router, and the compilation engine.

```python
# main.py
from pywire import PyWire

app = PyWire()
```

### Configuration Options

You can customize the application behavior by passing arguments to the constructor:

```python
app = PyWire(
    # Directory containing your .wire pages (default: "pages")
    pages_dir="src/pages",
    
    # Enable file-system based routing (default: True)
    path_based_routing=True,
    
    # Enable PJAX (smooth page transitions) (default: True)
    enable_pjax=True,
    
    # Enable debug mode (exposes source maps, etc.) (default: False)
    debug=True,
    
    # Path for static assets (default: "/static")
    static_path="/assets"
)
```

## Running the App

### Development

When you run `pywire dev`, the CLI automatically looks for a module exposing an `app` or `api` variable that is an instance of `PyWire`.

```bash
# Auto-discovery
pywire dev

# Explicit pointer
pywire dev src.main:app
```

### Production

For production, you use `pywire run`, which wraps Uvicorn.

```bash
pywire run src.main:app --workers 4
```

## Serving Static Files

If you have a `static/` directory in your project root, PyWire will automatically serve files from it at the `/static` URL prefix.

Example structure:

```text
project/
├── static/
│   ├── logo.png
│   └── styles.css
├── pages/
└── main.py
```

You can reference these in your templates:

```html
<img src="/static/logo.png" alt="Logo">
```
