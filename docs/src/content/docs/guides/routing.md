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

- `pages/posts/[slug].wire` -> `/posts/my-first-post` (accessible via `slug` variable on the page)
- `pages/users/[uid]/profile.wire` -> `/users/42/profile` (accessible via `uid` variable on the page)

## Explicit Routing

You can also define routes explicitly. First, set `path_based_routing` (default True) to False in your PyWire app init.

```python
from pywire import PyWire

app = PyWire(path_based_routing=False)
```

Then, add `!path` declarations to your pages.

```pywire
# A single route matching path
!path "/home"

<section>
    <h1>Home</h1>
</section>
```

You can match multiple routes, handle URL parameters, and automatically create SPA-like apps but with deep linking.

```pywire
# A single pages matching multiple paths
!path { "/home": "home", "/user/:uid": "user" }

<!-- Conditionally render based on route matched -->
<section>
    <h1 $if={path.home}>Home</h1>
    <h1 $if={path.user}>User {params.uid}</h1>
</section>
```

## Navigation

Standard `<a>` tags work out of the box. If `enable_pjax=True` (default), PyWire intercepts clicks on internal links and performs a "soft navigation" via `fetch` + HTML replacement, avoiding a full page reload.

```html
<a href="/about">About Us</a>
```
