---
title: Layouts
description: Reusing UI structures with layouts.
---

Layouts allow you to wrap multiple pages in a consistent UI structure (like headers, footers, and sidebars).

## Creating a Layout

A layout is just an ordinary `.wire` file that uses the `<slot />` tag to indicate where page content should be injected.

```html
<nav>
  <a href="/">Home</a>
  <a href="/about">About</a>
</nav>

<main>
  <slot />
</main>

<footer>© 2026 PyWire</footer>
```

## Using a Layout

Using a layout depends on whether your project uses path-based routing (default) or explicit routing.

### Layouts in Path-based Routing

The layout system functions similar to Svelte in this way--via hierarchy. You create your layout with the name `__layout__.wire` in the path where it should apply. For example, if you created a layout in the root of the pages directory, `src/pages/`, it would apply to all pages automatically

### Layouts in Explicit Routing

Since file path and hierarchy do not determine routing in projects using explicit routing, you can give your layout any name and put it in any file path. You can use a layout on a `.wire` page with the `!layout` directive.

```pywire
!path "/my-page"
!layout "path/to/layout.wire"

```
