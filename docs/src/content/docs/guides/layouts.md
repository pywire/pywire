---
title: Layouts
description: Reusing UI structures with layouts.
---

Layouts allow you to wrap multiple pages in a consistent UI structure (like headers, footers, and sidebars).

## Creating a Layout

A layout is just a `.wire` file that uses the `<slot />` tag to indicate where page content should be injected.

```html
<!-- layouts/main.wire -->
<nav>
    <a href="/">Home</a>
    <a href="/about">About</a>
</nav>

<main>
    <slot />
</main>

<footer>© 2024 PyWire</footer>
```

## Using a Layout

In your page file, specify the layout using the `layout` keyword in the Python block.

```html
# pages/index.wire
layout = "layouts/main.wire"

---html---
<h1>Welcome!</h1>
<p>This content is inside the layout.</p>
```

Layouts can also be nested by having a layout itself use another layout.
