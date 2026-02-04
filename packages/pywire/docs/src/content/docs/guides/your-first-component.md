---
title: Your First Component
description: Build a reactive counter component in PyWire.
---

Building a component in PyWire is as simple as writing HTML and adding a bit of Python for logic.

Let's look at a classic counter example.

```html
count = wire(0)

def increment():
    $count += 1

---html---
<button @click={increment}>
    Increment
</button>

<h1>Current Count: {count.value}</h1>

<div $if={count.value > 10}>
    Wow, you're clicking fast!
</div>
```

## Adding More Interactivity

You can use standard HTML attributes and even add conditional styling.

```html
count = wire(0)

def increment():
    $count += 1

---html---
<h1>Count: {count.value}</h1>

<button @click={increment} 
        $disabled={count.value >= 10}>
    Increment (Max 10)
</button>

<p $show={count.value > 5} style="color: red;">
    High count alert!
</p>
```

In the next sections, we'll dive deeper into the `.wire` file format and how reactivity works.
