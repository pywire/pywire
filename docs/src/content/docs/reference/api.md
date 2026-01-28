---
title: Core API Reference
description: Key decorators and functions in pywire.
---

## Decorators

### `@component`
Marks a function as a pywire component. These functions should return a string or a `pyhtml` object.

### `@mount`
A lifecycle hook that runs once when the component is first rendered in the browser.

## Runtime Helpers

### `$event`
Available inside event handlers to access common event properties (like `$event.value` for inputs).

### `relocate(path)`
A Python function to trigger a client-side navigation.
