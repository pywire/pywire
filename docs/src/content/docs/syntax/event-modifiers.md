---
title: Event Modifiers
description: Fine-tuning event behavior with modifiers.
---

PyWire supports several event modifiers to simplify common tasks like preventing default behavior, debouncing inputs, or limiting events to specific keys.

Modifiers are chained after the event name with dots: `@event.modifier={handler}`.

## Behavior Modifiers

### `.prevent`

Calls `event.preventDefault()`. Commonly used on form submissions and link clicks.

```pywire
<form @submit.prevent={handle_submit}>
    <button type="submit">Save</button>
</form>
```

### `.stop`

Calls `event.stopPropagation()`. Prevents the event from bubbling up to parent elements.

```pywire
<div @click={close_menu}>
    <button @click.stop={do_action}>
        Click me (won't close the menu)
    </button>
</div>
```

### `.once`

The event handler fires only once. After the first invocation, the listener is automatically removed.

```pywire
<button @click.once={initialize}>
    Initialize (can only click once)
</button>
```

## Keyboard Modifiers

Filter keyboard events to specific keys. The modifier name matches the key value (case-insensitive).

### `.enter`

Only triggers if the Enter key was pressed.

```pywire
<input @keydown.enter={submit_search} placeholder="Search..." />
```

### `.escape`

Only triggers on the Escape key.

```pywire
<div @keydown.escape={close_modal}>
    Modal content
</div>
```

### Other key modifiers

Use any key name as a modifier: `.space`, `.tab`, `.delete`, `.backspace`, `.up`, `.down`, `.left`, `.right`.

```pywire
<input @keydown.space={toggle_play} />
```

## Click Modifiers

### `.outside`

Triggers when a click occurs **outside** the element. Useful for closing dropdowns and modals.

```pywire
<div class="dropdown" @click.outside={close_dropdown}>
    Dropdown content
</div>
```

## Timing Modifiers

### `.debounce.Nms`

Delays the handler until N milliseconds have passed since the last event. Useful for search-as-you-type inputs.

```pywire
<input type="text"
       @input.debounce.300ms={search_users(event.value)}
       placeholder="Search users..." />
```

### `.throttle.Nms`

Ensures the handler is called at most once every N milliseconds. Useful for scroll or resize events.

```pywire
<div @scroll.throttle.100ms={handle_scroll}>
    Scrollable content
</div>
```

## Chaining Modifiers

Multiple modifiers can be chained together:

```pywire
<!-- Prevent default AND only fire once -->
<form @submit.prevent.once={handle_first_submit}>
    ...
</form>

<!-- Stop propagation AND debounce -->
<input @input.stop.debounce.200ms={search(event.value)} />
```

## Error Handling

The `.error` modifier allows you to catch validation errors or server-side exceptions for a specific event.

```pywire
<form @submit={save_data} @submit.error={handle_error}>
    ...
</form>
```

The `handle_error` function receives the exception that occurred during `save_data`.
