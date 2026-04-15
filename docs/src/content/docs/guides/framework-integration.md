---
title: Framework Integration
description: Mounting PyWire inside FastAPI, Starlette, or other ASGI frameworks.
---

PyWire can be mounted inside an existing ASGI application. This lets you add PyWire pages to a FastAPI or Starlette project without replacing your existing API routes.

## Mounting in FastAPI

```python
from fastapi import FastAPI
from pywire import PyWire

api = FastAPI()
pywire = PyWire(pages_dir="./pages", fallthrough_404=True)

# Mount at root — PyWire handles page routes, unmatched paths fall through
api.mount("/", pywire.as_asgi())

# Or mount at a prefix
api.mount("/app", pywire.as_asgi())
```

Your existing FastAPI routes continue to work:

```python
@api.get("/api/users")
async def get_users():
    return [{"name": "Alice"}, {"name": "Bob"}]
```

When a request arrives:
1. FastAPI checks its own routes first (`/api/users`, etc.)
2. If no match, the request falls through to PyWire
3. PyWire renders the matching `.wire` page
4. If PyWire has no match either, `fallthrough_404=True` returns a bare 404

## Mounting in Starlette

```python
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from pywire import PyWire

pywire = PyWire(pages_dir="./pages", fallthrough_404=True)

app = Starlette(routes=[
    Route("/api/health", health_handler),
    Mount("/", app=pywire.as_asgi()),
])
```

## Key Options

### `fallthrough_404`

When `True`, PyWire returns a bare 404 response for paths that don't match any `.wire` page. This lets the host framework try other routes or return its own 404 page.

When `False` (the default), PyWire renders its own 404 error page — suitable for standalone deployments where PyWire owns all routes.

```python
# Standalone — PyWire handles everything including 404s
app = PyWire()

# Mounted — let FastAPI handle unmatched paths
pywire = PyWire(fallthrough_404=True)
```

### `as_asgi()`

Returns the PyWire instance as an ASGI application. Since `PyWire` already implements `__call__`, this is primarily a semantic method — it signals intent to mount.

### `mount_in(root_app)`

When PyWire is mounted inside a host framework, internal request dispatch (used for SPA middleware parity) should go through the **host's** middleware stack. Call `mount_in()` to set this up:

```python
api = FastAPI()
pywire = PyWire(pages_dir="./pages", fallthrough_404=True)

api.mount("/app", pywire.as_asgi())
pywire.mount_in(api)  # Internal dispatch goes through FastAPI middleware
```

Without `mount_in()`, internal dispatch only goes through PyWire's own middleware. This means host-level auth, CORS, or rate limiting middleware won't apply to SPA navigations.

## Middleware Parity

A key benefit of PyWire's architecture: **middleware works transparently**. When a user clicks a link in a PyWire page, the framework dispatches an internal HTTP request through the full ASGI middleware stack — including any middleware added by the host framework.

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pywire import PyWire

api = FastAPI()
api.add_middleware(CORSMiddleware, allow_origins=["*"])

pywire = PyWire(pages_dir="./pages", fallthrough_404=True)
api.mount("/", pywire.as_asgi())
pywire.mount_in(api)

# CORS middleware now applies to both:
# - FastAPI API routes (direct HTTP)
# - PyWire SPA navigations (via internal dispatch)
```

## Shared Request Context

When mounted in FastAPI, `request.state` is shared. Data set by FastAPI middleware or dependencies is available in PyWire pages:

```python
# FastAPI middleware sets user info
@api.middleware("http")
async def add_user(request, call_next):
    request.state.user = get_user_from_token(request)
    return await call_next(request)
```

In your `.wire` page, access it via `self.request.state`:

```python
---
user = self.request.state.user
---
<h1>Welcome, {user.name}</h1>
```

## Path Prefix Handling

When mounted at a prefix (e.g., `/app`), PyWire automatically strips the prefix when matching routes. Your `.wire` pages define routes relative to the mount point:

```
pages/
  index.wire     → /app/
  dashboard.wire → /app/dashboard
  settings.wire  → /app/settings
```

Links between PyWire pages should use relative paths:

```html
<a href="/app/dashboard">Dashboard</a>
```
