---
title: Server-Side Events
description: Handling browser events in Python.
---

PyWire allows you to handle standard browser events (like clicks, inputs, and form submissions) directly in Python.

## Basic Event Handling

Use the `@` prefix followed by the event name to bind a Python function to a browser event.

```pywire

count = wire(0)

def handle_click():
    $count += 1

---html---
<button @click={handle_click}>
    Clicked {count.value} times
</button>
```

## Passing Data

You can pass data from the browser to your Python handlers.

```pywire

items = wire([{"id": 1, "name": "Item 1"}, {"id": 2, "name": "Item 2"}])

def delete_item(item_id):
    $items = [i for i in $items if i['id'] != item_id]

---html---
<ul>
    <li $for={item in items.value}>
        {item['name']}
        <button @click={delete_item(item['id'])}>Delete</button>
    </li>
</ul>
```

## Input Events

For input fields, you can use `@input` or `@change`.

```pywire

search_query = wire("")

def on_search(value):
    $search_query = value
    print(f"Searching for: {value}")

---html---
<input type="text" 
       placeholder="Search..." 
       @input={on_search($event.target.value)}>
```

We'll cover more advanced event features in the [Event Modifiers](/docs/syntax/event-modifiers) section.
