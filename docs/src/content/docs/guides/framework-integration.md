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
api.mount("/", pywire.as_asgi(api))

# Or mount at a prefix
api.mount("/app", pywire.as_asgi(api))
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

## Lifespan

A host app doesn't run the lifespan of apps mounted inside it, so PyWire's startup and shutdown (connecting its session store, flushing sessions on exit) would never run. Enter it from the host's lifespan:

```python
from contextlib import asynccontextmanager

ui = PyWire(pages_dir="src/pages", fallthrough_404=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.create_tables()
    async with ui.lifespan():
        yield
    await db.engine.dispose()


app = FastAPI(lifespan=lifespan)
app.mount("/", ui.as_asgi(app))
```

## Running it

Point the CLI at the host app. `pywire dev` finds the PyWire instance mounted inside it for hot reload and serves the whole FastAPI app:

```sh
pywire dev src.main:app
pywire run src.main:app --workers 1
```

## Pages and API together

Give pages and routes one service layer to call, and one set of Pydantic models:

```python
# schemas.py: FastAPI's request body and the page's form(TaskIn)
class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)

# api.py
@router.post("/boards/{board_id}/tasks", status_code=201)
async def create_task(board_id: int, data: TaskIn, actor: Me, db: Db) -> TaskOut:
    return await services.create_task(db, actor, board_id, data)
```

```python
# pages/boards/[board_id].wire
task_form = form(TaskIn)

async def add_task(data: TaskIn):
    async with db.session() as s:
        await services.create_task(s, actor_from(self.user), board_id, data)
    task_form.reset()
```

Pages use the session cookie (`self.user`); give the API bearer tokens so it doesn't depend on cookies. Plain FastAPI routes, including `@app.websocket(...)` routes, work next to pywire's own WebSocket. [Building Real Apps](/docs/guides/best-practices/) covers the service layer, live updates and access checks in more detail, and the [taskboard example](https://github.com/pywire/pywire/tree/main/examples/taskboard) is a complete app built this way.

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
# Set host after construction so SPA navigations go through Starlette middleware
pywire.as_asgi(app)
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

### `as_asgi(host=None)`

Returns the PyWire instance as an ASGI application for mounting. Pass the host application so that SPA navigations (via WebSocket) go through the host's full middleware stack:

```python
api.mount("/app", pywire.as_asgi(api))
```

Without `host`, internal dispatch only goes through PyWire's own middleware — suitable for standalone deployments. When a host is provided, every SPA navigation is replayed as an internal HTTP request through the host's middleware stack, so auth, CORS, and rate limiting apply uniformly.

## Middleware Parity

A key benefit of PyWire's architecture: **middleware works transparently**. When a user clicks a link in a PyWire page, the framework dispatches an internal HTTP request through the full ASGI middleware stack — including any middleware added by the host framework.

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pywire import PyWire

api = FastAPI()
api.add_middleware(CORSMiddleware, allow_origins=["*"])

pywire = PyWire(pages_dir="./pages", fallthrough_404=True)
api.mount("/", pywire.as_asgi(api))

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
