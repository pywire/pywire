---
title: Introduction
description: What is PyWire and why should you use it?
---

**PyWire** is a "Live Conduit" framework for building modern, reactive web applications using only Python. It bridges the gap between server-side logic and client-side interactivity without requiring you to write a single line of JavaScript.

## The Philosophy

Modern web development often requires maintaining two separate codebases: a backend API (Python, Go, Node) and a frontend SPA (React, Vue, Svelte). This adds complexity, duplicates logic (validation, types), and introduces synchronization headaches.

PyWire takes a different approach: **HTML-over-the-wire**.

1. **State Lives on the Server**: All application state is maintained in Python processes on the server.
2. **Logic is Python**: Event handlers, validation, and business logic are written in standard Python.
3. **The "Wire" Updates the View**: When state changes, PyWire calculates the minimal DOM updates required and sends them over a persistent WebSocket connection to the browser.

## Key Features

### 🐍 Python-First Reactivity

Define reactive variables using `wire()`. When you update them in your Python code, the UI updates automatically.

```python
count = wire(0)

def increment():
    $count += 1
```

### ⚡ No JavaScript Required

You write HTML templates and Python logic. The framework handles the client-side interactivity, event listeners, and DOM manipulation.

### 📂 File-System Routing

Create files in the `pages/` directory to automatically define routes, supporting dynamic parameters like `pages/users/[id].wire`.

### 🛠️ Developer Experience

Includes a robust CLI with a Terminal User Interface (TUI) for real-time logs, hot-reloading, and debugging tools.

## How it Works

A PyWire application consists of `.wire` files. These files are compiled into Python classes that handle:

- **Rendering**: Generating the initial HTML.
- **Hydration**: Establishing a WebSocket connection.
- **Events**: Receiving events (clicks, inputs) from the browser.
- **Updates**: Sending precise DOM patches back to the client.

Ready to see it in action? Let's [build your first component](/docs/guides/your-first-component).
