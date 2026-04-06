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

For more control, you can define routes explicitly using the `!path` directive. This is particularly powerful for Single-Page Application (SPA) architectures where one component handles multiple UI states while maintaining deep-linking capabilities.

To strictly enforce explicit routing, set `path_based_routing=False` in your `PyWire` app initialization.

```python
from pywire import PyWire

app = PyWire(path_based_routing=False)
```

### Multi-Route Components

A unique feature of PyWire's explicit routing is mapping multiple URL patterns to a single component. This allows you to centralize logic for related views.

```pywire
# Match both the home page and a user profile page
!path { "/home": "home", "/user/:uid": "user" }

<!-- Conditionally render based on the active route -->
<section>
    <div $if={path.home}>
        <h1>Welcome Home</h1>
    </div>
    
    <div $if={path.user}>
        <h1>User Profile: {params.uid}</h1>
    </div>
</section>
```

In this example:
- Visiting `/home` sets `path.home` to `True`.
- Visiting `/user/123` sets `path.user` to `True` and populates `params.uid`.

## Choosing a Strategy

| Feature | Path-Based (File-System) | Explicit (`!path`) |
| :--- | :--- | :--- |
| **Setup** | Zero config. Just create files. | Requires `!path` directive in files. |
| **Structure** | Strictly coupled to directory structure. | Decoupled. File location doesn't dictate URL. |
| **Complexity** | Best for simple, page-centric apps. | Best for complex UIs, "app-like" experiences. |
| **State** | Navigation always resets component state. | One component can handle route changes without unmounting (preserving state). |

### The Power of State Preservation

Explicit routing's biggest advantage is **state continuity**. In traditional file-system routing, navigating from `/users/alice` to `/users/bob` (even if they use the same `[slug].wire` file) typically unmounts the current component instance and mounts a new one, resetting all reactive state.

With Explicit Routing and a dictionary-based `!path`, the component instance **stays alive** when the URL matches a different key in the same dictionary. Only the `path` and `params` reactive objects update.

This is invaluable for:
- **Persistent Filters**: Keeping search filters active while clicking through result pages.
- **Background Tasks**: Allowing a file upload or long-running process to continue while the user navigates between sub-views of the same "App" component.
- **Transitions**: Orchestrating smooth animations between view states that would otherwise be interrupted by a page unmount.

**Recommendation:** Start with Path-Based routing for rapid prototyping. Switch to Explicit routing if you need a specific component to persist state across URL changes or if your UI hierarchy doesn't map cleanly to a folder structure.

## Navigation

Standard `<a>` tags work out of the box. If `enable_pjax=True` (default), PyWire intercepts clicks on internal links and performs a "soft navigation" via `fetch` + HTML replacement, avoiding a full page reload.

```html
<a href="/about">About Us</a>
```
