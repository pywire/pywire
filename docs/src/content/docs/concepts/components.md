---
title: Components
description: Building reusable UI pieces with .wire components.
---

PyWire components are `.wire` files that can be imported and used inside other pages or components. They follow standard Python import conventions, support props for data passing, and provide scoped styling.

## Creating a Component

Any `.wire` file can be a component. Place your components in a directory (e.g., `components/`) to keep them organized.

```pywire
<!-- components/greeting.wire -->
---
from pywire import props

@props
class Props:
    name: str
    greeting: str = "Hello"
---
<div class="greeting">
    <h2>{props.greeting}, {props.name}!</h2>
</div>

<style scoped>
    .greeting {
        padding: 1rem;
        border: 1px solid #e2e8f0;
        border-radius: 0.5rem;
    }
</style>
```

## Importing Components

Import components using Python's standard dot notation. The class name matches the file name in PascalCase.

```pywire
---
from components.greeting import Greeting
---
<div>
    <Greeting name="Alice" />
    <Greeting name="Bob" greeting="Welcome" />
</div>
```

Nested directories work naturally:

```py
from lib.ui.buttons.primary_button import PrimaryButton
from shared.layouts.sidebar import Sidebar
```

## Props

Props define the data a component accepts from its parent. Use the `@props` decorator on a class to declare them.

```pywire
---
from pywire import props

@props
class Props:
    title: str                    # Required prop
    count: int = 0                # Optional with default
    color: str = "blue"           # Optional with default
---
<h1 style={f"color: {props.color}"}>{props.title} ({props.count})</h1>
```

Props are accessed via the `props` object in templates and the Python block. See the [API Reference](/docs/reference/api) for more details.

## Attribute Spreading

Any attributes passed to a component that aren't declared in `@props` are collected into `attrs`. Use `{**attrs}` to spread them onto an element:

```pywire
<!-- components/button.wire -->
<button class="btn" {**attrs}>
    {$render children}
</button>
```

```pywire
<!-- Usage: all extra attributes pass through to <button> -->
<Button type="submit" disabled={!valid} aria-label="Save">
    Save
</Button>
```

## Children and Named Snippets

Every component receives an implicit `children` prop holding whatever markup the parent wrote between the tags. Render it with `{$render children}`:

```pywire
<!-- components/card.wire -->
<div class="card">
    {$render children}
</div>
```

```pywire
<!-- Usage -->
<Card>
    <h2>Card Title</h2>
    <p>Card content goes here.</p>
</Card>
```

For **multiple named regions** (header, footer, sidebar, etc.), define a named snippet in the parent and render it in the component. The paired form provides a fallback when the snippet isn't supplied:

```pywire
<!-- components/card.wire -->
<div class="card">
    <header>{$render header}Untitled{/render}</header>
    {$render children}
</div>
```

```pywire
<!-- Usage -->
<Card>
    {$snippet header}Product Details{/snippet}
    <p>Body content here.</p>
</Card>
```

Snippets can also take parameters — useful for list rendering where the component owns the loop:

```pywire
<!-- components/list.wire -->
---
from pywire import props

@props
class Props:
    items: list
---
<ul>
    <li $for={item in props.items}>
        {$render row(item)}
    </li>
</ul>
```

```pywire
<!-- Usage -->
<List items={todos}>
    {$snippet row(todo)}
        <input type="checkbox" checked={todo.done}> {todo.text}
    {/snippet}
</List>
```

### Typing `children` and named snippets

PyWire exposes two annotation aliases for snippet-valued props:

| Annotation                                    | Meaning                                                                                                  |
| --------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `Snippet`                                     | Any snippet value. Most general.                                                                         |
| `Snippet[A, B]`                               | Snippet taking typed parameters `(A, B)`. Carried through to tooling.                                    |
| `Child`                                       | Single-child shorthand. Alias of `Snippet` — documents that the caller should pass exactly one fragment. |
| `Children`                                    | Many-children shorthand. Same runtime representation as `Snippet`.                                       |
| `Children[n]` / `Children.of(min=, max=, n=)` | Declares expected cardinality for editor tooling and future validation.                                  |

```pywire
---
from pywire import props
from pywire import Snippet, Child, Children

@props
class Props:
    children: Child                  # exactly one child
    header:   Snippet                # zero-arg snippet
    row:      Snippet[dict]          # called with one dict arg per row
    tabs:     Children.of(min=1)     # at least one tab
---
```

These are **type hints first** — they describe intent and are read by the LSP and prettier. Runtime cardinality enforcement for `Children[...]` is a planned follow-up; today the values themselves behave identically to `Snippet`.

## Scoped Styles

Add a `<style scoped>` block to any `.wire` file to scope CSS to that component. Scoped styles won't leak to parent or sibling components.

```pywire
<button class="btn">Click me</button>

<style scoped>
    .btn {
        background: #3b82f6;
        color: white;
        border: none;
        padding: 0.5rem 1rem;
        border-radius: 0.25rem;
        cursor: pointer;
    }
    .btn:hover {
        background: #2563eb;
    }
</style>
```

## Raw HTML (`{$html}`)

By default, all interpolated values are HTML-escaped. To render trusted HTML strings, use the `{$html ...}` directive:

```pywire
---
bio = "<strong>Alice</strong> is a developer."
---
<div>{$html bio}</div>
```

> [!CAUTION]
> Never use `{$html ...}` with untrusted user input — it bypasses XSS protection.

## Component Refs

Parents can get a reference to a child component using `$ref` and call any method decorated with `@expose`:

```pywire
---
from pywire import ref
from components.modal import Modal

modal_ref = ref()
---
<button @click={modal_ref.open()}>Open</button>
<Modal $ref={modal_ref}>Content</Modal>
```

See [`expose`](/docs/reference/api#expose) and [`ref`](/docs/reference/api#ref) in the API reference.
