---
title: Event Modifiers
description: Fine-tuning event behavior with modifiers.
---

PyWire supports several event modifiers to simplify common tasks like preventing default behavior or debouncing inputs.

## Common Modifiers

- `.prevent`: Calls `event.preventDefault()`.
- `.stop`: Calls `event.stopPropagation()`.
- `.enter`: Only triggers if the "Enter" key was pressed.
- `.outside`: Triggers when a click occurs outside the element.

```html
<form @submit.prevent="{handle_submit}">
  <input @keydown.enter="{add_item}" />
  <button>Submit</button>
</form>

<div class="modal" @click.outside="{close_modal}">Modal Content</div>
```

## Input Modifiers

- `.debounce.ms`: Delays the event handler until a specified number of milliseconds have passed since the last event.
- `.throttle.ms`: Ensures the event handler is called at most once every specified number of milliseconds.

```html
<input type="text" @input.debounce.300ms={search_users(event.value)} />
```

## Error Handling

The `.error` modifier allows you to catch validation errors or server-side exceptions for a specific event.

```html
<form @submit="{save_data}" @submit.error="{handle_error}">...</form>
```
