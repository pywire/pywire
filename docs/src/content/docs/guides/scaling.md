---
title: Horizontal Scaling
description: Scaling PyWire across multiple workers and machines.
---

## How PyWire handles state

PyWire holds WebSocket session state in worker process memory. This is fast and simple, but has implications for scaling:

- **Single worker** — everything works out of the box. Sessions persist for the connection lifetime.
- **Multiple workers** — requests may hit different processes. Without shared state, sessions break.
- **Multiple machines** — same issue, amplified across separate servers.

## Scaling with Redis or Valkey

PyWire has built-in support for [Redis](https://redis.io/) and Redis-compatible stores like [Valkey](https://valkey.io/), [Dragonfly](https://www.dragonflydb.io/), and [KeyDB](https://docs.keydb.dev/).

### Setup

Three steps to enable multi-worker scaling:

1. **Install the Redis extra:**

   ```sh
   uv add pywire[redis]
   ```

2. **Set the `REDIS_URL` environment variable:**

   ```sh
   export REDIS_URL=redis://localhost:6379
   ```

3. **Increase workers:**

   ```sh
   pywire run --workers 4
   ```

That's it. PyWire auto-detects `REDIS_URL` at startup and uses it for session persistence — no code changes needed.

### How it works

After each event handler executes, PyWire serializes page state and persists it to Redis. On WebSocket reconnect (or when a different worker handles the next request), state is restored from Redis into a fresh page instance.

**What gets persisted:**

- Wire values (via `.peek()`)
- Component state snapshots
- `errors` and `loading` dicts
- `user` attribute
- Route path and page class

**What gets rebuilt naturally:**

- Dependency tracking (`_wire_subscribers`, `_region_dependencies`)
- Background tasks
- Request object
- Component instances (from snapshots)

Session TTL defaults to **30 minutes** and is configurable:

```python
app = PyWire(session_ttl=3600)  # 1 hour
```

### Explicit configuration

For full control, pass a session store directly instead of relying on auto-detection:

```python
from pywire import PyWire
from pywire.runtime.redis_store import RedisSessionStore

app = PyWire(
    session_store=RedisSessionStore("redis://localhost:6379"),
    session_ttl=3600,
)
```

### Environment variables

| Variable        | Description                                             |
| --------------- | ------------------------------------------------------- |
| `REDIS_URL`     | Redis/Valkey connection string (checked first)          |
| `FLY_REDIS_URL` | Fly.io Upstash Redis URL (fallback if `REDIS_URL` unset) |

### Custom session stores

For backends other than Redis, implement the `SessionStore` protocol:

```python
from pywire.runtime.session_store import SessionStore

class MyStore(SessionStore):
    async def get(self, session_id: str) -> dict | None: ...
    async def set(self, session_id: str, data: dict, ttl: int | None = None) -> None: ...
    async def delete(self, session_id: str) -> None: ...
    async def exists(self, session_id: str) -> bool: ...
    async def touch(self, session_id: str, ttl: int | None = None) -> None: ...
    async def close(self) -> None: ...
```

Pass it to `PyWire(session_store=MyStore())`.

## Platform guides

### Docker / Docker Compose

Single container with multiple workers:

```sh
docker run -p 8000:8000 -e REDIS_URL=redis://your-redis:6379 my-app
```

Multiple containers with a shared Redis instance (`docker-compose.yaml`):

```yaml
services:
  web:
    build: .
    ports: ["8000:8000"]
    environment:
      REDIS_URL: redis://redis:6379
    depends_on: [redis]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
```

### Render

Use `pywire deploy --platform render --redis --workers 4` to generate a `render.yaml` with a KV store pre-configured. Render provisions the Redis instance and injects `REDIS_URL` automatically.

Or add one manually:

```yaml
services:
  - type: web
    name: my-app
    runtime: docker
    plan: starter
    envVars:
      - key: REDIS_URL
        fromService:
          name: my-app-kv
          type: keyvalue
          property: connectionString

  - type: keyvalue
    name: my-app-kv
    plan: starter
    ipAllowList: []
```

Use `plan: standard` or higher for persistence across restarts.

### Fly.io

**Option A — Sticky sessions** (simple, limited): Fly Proxy can route all requests from a session to the same machine using `fly-replay`. Works for light scaling but breaks with VPNs and corporate proxies.

**Option B — Redis** (recommended): Add Upstash Redis:

```sh
fly redis create
fly secrets set REDIS_URL=<connection-string>
```

Install `pywire[redis]` and increase workers in your Dockerfile.

### Railway

Add a Redis addon via the Railway dashboard or `railway add`. Railway injects `REDIS_URL` automatically. Install `pywire[redis]` and increase `--workers` in your Dockerfile.

### Generic cloud / VPS

Any Redis-compatible KV store works:

- **AWS**: ElastiCache for Redis
- **GCP**: Memorystore for Redis
- **Azure**: Azure Cache for Redis
- **Self-hosted**: Redis, Valkey, Dragonfly, or KeyDB

Set `REDIS_URL`, install `pywire[redis]`, and increase workers.

## Cost and resource considerations

- **Single worker is free** on most platforms and sufficient for small apps with few concurrent users.
- **Redis adds a separate service** to your infrastructure. Most cloud providers charge for it separately.
- **Render**: Free tier has no KV. `starter` plan KV starts at $7/month.
- **Fly.io**: Upstash Redis has a free tier (limited commands/month).
- **Railway**: Redis addon pricing varies by usage.

Only add Redis when you actually need multiple workers or machines. For most apps in early development, `--workers 1` is the right choice.
