---
title: Interpolation & Attributes
description: Binding data to your HTML templates.
---

PyWire templates use a simple syntax for embedding Python values and binding attributes.

## Interpolation

Use curly braces `{}` to embed Python expressions directly into your HTML.

```pywire

user = wire(name="Alice")

---html---
<h1>Hello, {user.name}</h1>
<p>The result is {10 * 5}</p>
<p>Status: {get_status_message()}</p>
```

## Attribute Binding

There are two ways to bind attributes dynamically:

### Reactive Attributes

Use brackets instead of quotes to bind an attribute to a Python expression. It follows the same reactivity rules as interpolation.

```pywire

is_active = wire(True)
theme_color = wire("blue")

---html---
<div class={{'active': $is_active}}" 
     style={f"color: {theme_color.value}"}>
    Dynamic content
</div>
```
