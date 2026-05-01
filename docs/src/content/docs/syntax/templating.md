---
title: Interpolation & Attributes
description: Binding data to your HTML templates.
---

PyWire templates use a simple syntax for embedding Python values and binding attributes.

## Interpolation

Use curly braces `{}` to embed Python expressions directly into your HTML.

```pywire
---
user = wire(name="Alice")
---
<h1>Hello, {user.name}</h1>
<p>The result is {10 * 5}</p>
<p>Status: {get_status_message()}</p>
```

Interpolated values are **HTML-escaped** by default to prevent XSS attacks. To render raw HTML, use the `{$html ...}` directive:

```pywire
---
content = "<strong>Bold</strong> and <em>italic</em>"
---
<!-- Escaped (displays as text) -->
<p>{content}</p>

<!-- Raw HTML (renders as HTML) -->
<div>{$html content}</div>
```

> [!CAUTION]
> Never use `{$html ...}` with untrusted user input.

## Attribute Binding

There are several ways to bind attributes dynamically.

### Expression Binding

Use curly braces instead of quotes to bind an attribute to a Python expression.

```pywire
---
is_active = wire(True)
theme_color = wire("blue")
---
<div class={f"card {'active' if is_active else ''}"}
     style={f"color: {theme_color}"}>
    Dynamic content
</div>
```

### Shorthand Binding

When the attribute name and variable name are the same, you can use a shorthand syntax:

```pywire
---
src = "https://example.com/image.png"
id = "main-image"
---
<!-- These are equivalent -->
<img src={src} id={id} />
<img {src} {id} />
```

### `class` and `style` Bindings

The `class` and `style` attributes accept structured values in addition to plain strings, so you don't have to build the string yourself.

**`class`:**

- **String** — passes through unchanged.
- **List / tuple** — truthy items are space-joined; falsy items are dropped.
- **Dict** — keys whose values are truthy are space-joined.

```pywire
---
is_active = wire(True)
is_disabled = wire(False)
size = wire("lg")
---
<!-- list form -->
<button class={["btn", size, is_active and "active"]}>Click</button>

<!-- dict form (the most readable for many flags) -->
<button class={{"btn": True, "active": is_active, "disabled": is_disabled}}>
    Click
</button>
```

**`style`:**

- **String** — passes through unchanged.
- **Dict** — `key: value` pairs are joined with `;`. Entries with `None` values are dropped.

```pywire
---
theme = wire("dark")
---
<div style={{"color": "red", "background": theme, "border": None}}>
    Styled content
</div>
```

### Boolean Attributes

Framework attributes like `$disabled`, `$checked`, and `$readonly` accept a boolean expression and add or remove the attribute accordingly.

```pywire
---
count = wire(0)
accepted = wire(False)
---
<button @click={count.value += 1} $disabled={count >= 10}>
    Increment (Max 10)
</button>

<input type="checkbox" @change={accepted.value = event.checked} />
<button $disabled={not accepted}>Submit</button>
```

## Attribute Spreading

Components can accept arbitrary attributes using the spread operator `{**attrs}`. Any attributes not captured by `@props` are collected into `attrs` and can be spread onto an element.

```pywire
<!-- components/custom_input.wire -->
<div class="input-wrapper">
    <input {**attrs} />
</div>
```

```pywire
<!-- Usage -->
---
from components.custom_input import CustomInput
---
<CustomInput placeholder="Search..." type="text" class="search-box" />
```

All three attributes (`placeholder`, `type`, `class`) pass through to the `<input>` element.
