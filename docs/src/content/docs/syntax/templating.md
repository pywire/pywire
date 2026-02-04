---
title: Interpolation & Attributes
description: Binding data to your HTML templates.
---

PyWire templates use a simple syntax for embedding Python values and binding attributes.

## Interpolation

Use curly braces `{}` to embed Python expressions directly into your HTML.

```html
user = wire({"name": "Alice"})

---html---
<h1>Hello, {user.name}</h1>
<p>The result is {10 * 5}</p>
<p>Status: {get_status_message()}</p>
```

## Attribute Binding

There are two ways to bind attributes dynamically:

### Reactive Attributes (`:`)

Use the colon `:` prefix to bind an attribute to a Python value. The attribute will be updated whenever the value changes.

```html
is_active = wire(True)
theme_color = wire("blue")

---html---
<div :class="{ 'active': is_active.value }" 
     :style="f'color: {theme_color.value}'">
    Dynamic content
</div>
```

### Conditional Attributes (`$`)

Use the dollar `$` prefix for boolean attributes. The attribute will only be present if the expression evaluates to `true`.

```html
is_loading = wire(False)

---html---
<button $disabled={is_loading.value}>
    Submit
</button>
```

Common conditional attributes include `$disabled`, `$readonly`, `$checked`, and `$selected`.
