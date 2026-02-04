---
title: Testing
description: Testing your PyWire components and applications.
---

PyWire is designed with testability in mind. You can use standard Python testing tools like `pytest`.

## Unit Testing

You can test your component logic by importing the compiled Python classes.

## Integration Testing

For full integration tests, we recommend using [Playwright](https://playwright.dev/python/) to simulate user interactions in a real browser.

```python
def test_counter(page):
    page.goto("http://localhost:3000")
    page.click("button:has-text('Increment')")
    assert page.inner_text("h1") == "Current Count: 1"
```
