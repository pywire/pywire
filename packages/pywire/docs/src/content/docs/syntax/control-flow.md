---
title: Control Flow ($if, $for)
description: Conditional rendering and loops in PyWire templates.
---

PyWire provides special attributes for controlling the structure of your HTML.

## Conditional Rendering (`$if`)

Use `$if` to conditionally include an element in the DOM.

```pywire

user = wire(None)

---html---
<div $if={user.value}>
    Welcome back, {user.name}!
</div>
```

## Loops (`$for`)

Use `$for` to render a list of items.

```pywire

items = wire(["Apple", "Banana", "Cherry"])

---html---
<ul>
    <li $for={item in items.value}>
        {item}
    </li>
    <li $if={len(items) == 0}>
        No items found.
    </li>
</ul>
```

## Visibility (`$show`)

Unlike `$if`, which adds or removes elements from the DOM, `$show` toggles the `display: none` CSS property. Use this for elements that need to toggle frequently without full DOM reconstruction.

```pywire

is_visible = wire(False)

---html---
<div $show={is_visible.value}>
    I'm hidden but still in the DOM!
</div>
```
