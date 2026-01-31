---
title: 'Walkthrough: A Reactive Counter'
description: 'Building your first interactive component.'
---

In this walkthrough, we'll build a reactive counter that updates instantly without any JavaScript.

## 1. Create the File

Create a file named `counter.wire`.

## 2. Define the Component

A pywire component is just a Python function decorated with `@component`.

```python
@component
def Counter():
    count = 0

    def increment():
        nonlocal count
        count += 1

    return """
    <div class="counter">
        <p>The current count is: <strong>{count}</strong></p>
        <button @click="increment">Click Me!</button>
    </div>
    """
```

## 3. How it Works

- **State**: The `count` variable is kept in sync between the server and the browser.
- **Events**: The `@click="increment"` attribute tells pywire to call your Python `increment` function when the button is clicked.
- **Reactivity**: When the Python state changes, pywire automatically "morphs" the browser DOM to match the new HTML output.

## 4. Preview

Run `pywire dev` and navigate to the page to see your live counter in action.
