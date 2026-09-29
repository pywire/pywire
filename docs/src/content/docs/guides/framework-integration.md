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

## Serving under a path prefix

An app can live below the site root: mounted at `/app` in a host app, or behind a proxy that sends `example.com/demo/*` to it. Write the app as if it ran at `/`, and PyWire adds the prefix on the way out:

```
pages/
  index.wire     → /app/
  dashboard.wire → /app/dashboard
  settings.wire  → /app/settings
```

```html
<a href="/dashboard">Dashboard</a>
<!-- sent as href="/app/dashboard" -->
<link rel="stylesheet" href="/static/app.css" />
<!-- sent as /app/static/app.css -->
```

What gets the prefix:

- Root-relative `href`, `src`, `action`, `formaction`, `poster` and `srcset` in rendered HTML.
- `navigate("/x")`, `!auth` redirects, and the `Location` of any redirect the app returns.
- Cookie paths: `Path=/` becomes `Path=/app`, so two apps on one domain keep their cookies apart.
- The client's own URLs: the WebSocket, uploads, stateless posts and `asset()`.

What doesn't:

- Absolute (`https://…`) and relative (`page`, `?q=1`, `#top`) URLs.
- URLs that already start with the prefix, so `href="/app/dashboard"` keeps working.
- Anything inside `<script>` and `<style>`, and `url(...)` in CSS files. Use relative URLs in CSS. Pages have a `base_path` variable (`""` at the site root) to hand to scripts, for example `<main data-base={base_path}>` read by `fetch(main.dataset.base + "/api/items")`.
- Elements marked `data-pw-no-base`, for links that leave the app: `<a href="/" data-pw-no-base>All demos</a>`.

### Mounted in a host app

A host mount sets the ASGI `root_path`, and PyWire reads the prefix from it. So does a server started with `--root-path` (`uvicorn --root-path /app`), which is how a host app behind a stripping proxy learns its prefix.

### Behind a proxy that strips the prefix

When a proxy forwards `example.com/demo/chat` as `/chat` and the server isn't told, set `base_path`:

```python
app = PyWire(base_path="/demo")
```

or `PYWIRE_BASE_PATH=/demo` in the environment, so the same code runs at `/` locally. Requests work with the prefix stripped or not. With a host mount too, `base_path` goes in front of the mount path: `base_path="/demo"` and a mount at `/app` serve pages at `/demo/app/`.
