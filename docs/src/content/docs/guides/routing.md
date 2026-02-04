---
title: Routing
description: Defining routes in PyWire.
---

PyWire supports both file-system based routing and explicit routing.

## File-System Routing

By default, PyWire looks in the `pages/` directory and automatically creates routes based on the file structure.

- `pages/index.wire` -> `/`
- `pages/about.wire` -> `/about`
- `pages/contact/index.wire` -> `/contact`

### Dynamic Routes

Use square brackets to define dynamic parameters.

- `pages/posts/[slug].wire` -> `/posts/my-first-post` (accessible via `self.params['slug']`)
- `pages/users/[id]/profile.wire` -> `/users/42/profile`

## Explicit Routing

You can also define routes manually using the `@app.page` decorator.

```python
from pywire import PyWire

app = PyWire(path_based_routing=False)

@app.page("/")
def home():
    return "index.wire"

@app.page("/users/{id}")
def user_profile(id: int):
    return "profile.wire"
```

## Navigation

Standard `<a>` tags work out of the box. If `enable_pjax=True` (default), PyWire intercepts clicks on internal links and performs a "soft navigation" via `fetch` + HTML replacement, avoiding a full page reload.

```html
<a href="/about">About Us</a>
```

To force a full page reload, add the `wire-ignore` attribute.

```html
<a href="/external" wire-ignore>External Link</a>
```
