---
title: Server-Side Events
description: Handling browser events in Python.
---

PyWire allows you to handle standard browser events (like clicks, inputs, and form submissions) directly in Python.

## Basic Event Handling

Use the `@` prefix followed by the event name to bind a Python function to a browser event.

```pywire
---
count = wire(0)

def handle_click():
    count.value += 1
---
<button @click={handle_click}>
    Clicked {count} times
</button>
```

## Passing Data

Call a handler with arguments to pass it values from the render, such as the
row a button belongs to.

```pywire
---
items = wire([{"id": 1, "name": "Item 1"}, {"id": 2, "name": "Item 2"}])

def delete_item(item_id):
    items.value = [i for i in items if i['id'] != item_id]
---
<ul>
    <li $for={item in items}>
        {item['name']}
        <button @click={delete_item(item['id'])}>Delete</button>
    </li>
</ul>
```

## Input Events

For input fields, you can use `@input` or `@change`.

```pywire
---
search_query = wire("")

def on_search(value):
    search_query.value = value
    print(f"Searching for: {value}")
---
<input type="text"
       placeholder="Search..."
       @input={on_search(event.value)}>
```

PyWire automatically provides the `event` context variable (alias `$event`) in inline handlers. Alternatively, if you bind the function directly (e.g., `@input={on_search}`), PyWire passes the event to a parameter named `event` (or to the first required one) and event fields to parameters named after them:

| Parameter                                                                                                       | Event field                    |
| --------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| `value`, `values`, `checked`, `input_type`                                                                      | the element's current value(s) |
| `form_data`                                                                                                     | a submitted form's fields      |
| `key`, `code`, `key_code`, `alt_key`, `ctrl_key`, `meta_key`, `shift_key`                                       | keyboard state                 |
| `client_x`, `client_y`, `offset_x`, `offset_y`, `page_x`, `page_y`, `screen_x`, `screen_y`, `button`, `buttons` | mouse state                    |
| `type`, `id`, `name`, `target_id`, `target_name`, `target_tag`                                                  | the event type and the element |
| `detail`                                                                                                        | a custom event's detail        |

Any other parameter keeps its default: `def rename(value, is_admin=False)` never gets `is_admin` from the browser.

## What the Client Controls

Handlers run on the server, but the browser decides when to send an event and
what it holds. Treat the two kinds of input differently:

- **Event data is user input.** `event.value`, `form_data`, `key`, the
  parameters in the table above and anything else read from `event` come from
  the browser, and a user can send any value there, whatever the HTML allowed.
  Validate it like any request data (a [bound form](/docs/guides/forms)
  validates against its model for you).
- **Call arguments come from the server.** In
  `@click={delete_item(item['id'])}`, `item['id']` is evaluated when the page
  renders. PyWire signs the values into the element with the app's
  `secret_key` (or a key its processes share when there is none), and the
  handler receives exactly what was rendered. A client can repeat a click it
  was shown, but it cannot change the id, move it to another handler or page,
  or add arguments of its own; an event with arguments the page did not sign is
  refused. The signature does not expire: a user who was once shown the
  button can send it again later, so a handler that acts on data another user
  could own should still check the current user's access.
- **Page state stays on the server**, except in
  [stateless mode](/docs/guides/stateless-mode), where it travels signed. The
  client changes it only through your handlers and `$bind`.

Arguments are JSON values: numbers, strings, booleans, `None`, lists and
dicts (tuples arrive as lists). Pass an id and look the record up in the
handler rather than passing the record itself.

We'll cover more advanced event features in the [Event Modifiers](/docs/syntax/event-modifiers) section.
