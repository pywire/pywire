---
title: Getting Started
description: How to install and start using pywire.
---

Welcome to **pywire**, the "Live Conduit" for Python. 

## Installation

pywire is available on PyPI. You can install it using `uv` or `pip`:

```bash
uv add pywire
# or
pip install pywire
```

## Your First .wire File

pywire components are defined in `.wire` files. These files combine Python logic and HTML structure.

```python title="hello.wire"
@component
def Hello(name="World"):
    return f"""
    <div class="greeting">
        <h1>Hello, {name}!</h1>
        <p>This is a live conduit between Python and your browser.</p>
    </div>
    """
```

## Running the Development Server

To see your components in action, use the pywire CLI:

```bash
pywire dev
```

This will start a development server at `http://localhost:8000`.
