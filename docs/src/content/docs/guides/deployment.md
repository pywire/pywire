---
title: Deployment
description: Deploying your PyWire application to production.
---

PyWire applications can be deployed as long-running ASGI services or as stateless FaaS/edge functions. See [Edge & serverless deployment](/guides/edge-serverless-deployment/) to choose a tier and [Provider quickstarts](/guides/stateless-provider-quickstarts/) for generated platform commands.

## `pywire deploy`

The fastest way to get deployment configs is the `deploy` command. It builds your project and generates platform-specific configuration files.

```sh
pywire deploy --platform docker
```

### Platforms

**Docker** (default) — generates a `Dockerfile`:

```sh
pywire deploy --platform docker
```

The generated Dockerfile uses `python:3.12-slim`, installs dependencies with `uv`, and runs the app with `pywire run`.

**Render** — generates a `render.yaml`:

```sh
pywire deploy --platform render
```

After generating, push to your Git repo and connect it to [Render](https://render.com). The `render.yaml` configures a web service with the correct build and start commands.

**Fly.io** — generates a `fly.toml` and a `Dockerfile`:

```sh
pywire deploy --platform fly
```

Then deploy with the Fly CLI:

```sh
# One-time setup
fly launch --no-deploy   # imports fly.toml

# Deploy
fly deploy
```

To scale to multiple machines (`fly scale count N`), you need sticky sessions or a shared Redis instance — see [Horizontal Scaling](/docs/guides/scaling/).

**Railway** — generates a `railway.json` and `Dockerfile`:

```sh
pywire deploy --platform railway
```

Railway auto-detects the Dockerfile. Deploy with the [Railway CLI](https://docs.railway.com/guides/cli):

```sh
railway login && railway init
railway up
```

**Cloudflare Workers** — generates `wrangler.toml`, `entry.py`, and `pywire_do.py`. For a `src.main:app` layout, `entry.py` and `pywire_do.py` go in `src/` (with the build output from `pywire build --platform cloudflare`), so wrangler uploads only your app, not your tests or virtual environments. After the first run, `wrangler.toml` is yours: `pywire build` leaves it alone and warns if it lacks the app's Durable Object binding.

```sh
pywire deploy --platform cloudflare
```

:::caution[Paid plan required]
Cloudflare Python Workers requires a [Workers Paid plan](https://dash.cloudflare.com/workers/plans) ($5/month). The free plan's 3 MiB size limit and startup CPU limits are incompatible with Python frameworks.
:::

The app runs in **Durable Objects** placed near your visitors: one per Cloudflare region (western and eastern North America, South America, western and eastern Europe, Asia-Pacific, Oceania, Africa and the Middle East), created on first use. The Worker sends every page load, WebSocket and long-poll request to the object for the visitor's region. Each object runs the whole app, the way one `pywire run --workers 1` process does: each tab gets its own page, and module-level wires are shared by everyone in that region. Static assets are served from Cloudflare's edge CDN and never reach an object.

Visitors in different regions don't share module-level wires, just as two worker processes on a server don't. To run one object for everyone, so that all visitors share them, set a Worker var in `wrangler.toml`:

```toml
[vars]
PYWIRE_PLACEMENT = "global"
```

A single object lives near whoever reached it first, so visitors far from it pay the extra round trip.

This target serves stateful apps, and the build refuses a `PyWire(stateless=True)` app. Deploy a stateless app to a plain Worker with `--platform cloudflare-edge` instead (see [Provider quickstarts](/guides/stateless-provider-quickstarts/)).

**Local development:**

```sh
# Standard PyWire dev server (fast hot-reload, recommended for daily dev)
pywire dev

# Cloudflare Workers local runtime (tests workerd compatibility)
pywire build --platform cloudflare
uv run pywrangler dev
```

**Deploy:**

```sh
pywire build --platform cloudflare
uv run pywrangler deploy
```

**Architecture notes:**

- Each object runs one thing at a time, like one server process, so it suits the traffic one `pywire run --workers 1` process can take.
- An object stays in memory while anyone is connected to it. When everyone has left, or after a deploy, Cloudflare may evict it, and its module-level state and open pages start over, as after a server restart.
- Worker variables and secrets reach `os.environ` before your app is imported, so set `PYWIRE_SECRET_KEY` and your app's own settings with `wrangler secret put` or `[vars]`.
- `--workers` and `--redis` flags are not applicable.

**Current limitations:**

- **Cold starts (2-4 seconds):** Cloudflare Python Workers have cold start latency from restoring the Pyodide (WebAssembly Python) snapshot. Only the first visitor in a region after its object starts waits for it; later page loads and sockets reuse the running object.
- **Pydantic needs a recent compatibility date:** `pywire[forms]` (pydantic) runs on Python Workers from compatibility date 2026-09-01 (Pyodide 0.28), which the generated `wrangler.toml` sets. Older dates fail when `pywrangler` installs the dependencies.
- **Platform maturity:** Cloudflare Python Workers launched in late 2024 and is actively being improved. Cold start performance is expected to improve as Cloudflare optimizes Pyodide snapshot restoration and Durable Object initialization. Follow [Cloudflare's Python Workers changelog](https://developers.cloudflare.com/changelog/) for updates.

For latency-sensitive applications, container-based deployments (Docker, Railway, Render, Fly.io) provide sub-100ms WebSocket connections with no cold start penalty.

### Options

| Flag         | Description                                                                                |
| ------------ | ------------------------------------------------------------------------------------------ |
| `--platform` | Target platform: `docker`, `render`, `fly`, `railway`, or `cloudflare` (default: `docker`) |
| `--workers`  | Number of worker processes — not applicable to `cloudflare` (default: `1`)                 |
| `--redis`    | Include Redis/Valkey KV store in deployment config — not applicable to `cloudflare`        |
| `--out-dir`  | Output directory for generated files (default: `.`)                                        |

Use `--redis --workers 4` to generate configs pre-configured for multi-worker scaling. See [Horizontal Scaling](/docs/guides/scaling/) for details.

The command validates your project before generating configs. If `pyproject.toml` or `uv.lock` is missing, you'll see a warning.

## HTTP-only session mode

For a long-running host that cannot maintain persistent WebSocket connections, PyWire can use HTTP-session transport. This is different from FaaS stateless mode: HTTP-session still stores page state in a session cookie plus the configured session store.

```python
from pywire import PyWire

app = PyWire(interactive_server_mode=False)
```

Use this mode for a container/server without WebSocket support. For Lambda, Azure Functions, GCP Cloud Functions, or a plain Cloudflare Worker, use [`PyWire(stateless=True)`](/guides/stateless-mode/) instead; those targets are request-scoped and do not keep session state between invocations.

### How It Works

When `interactive_server_mode=False`:

- **No WebSocket endpoint** is registered. No persistent connections.
- **SPA navigation uses `fetch()`** — the client fetches new page HTML via HTTP and applies it with morphdom (same smooth transitions).
- **Session state** is persisted via a signed httponly cookie and the session store (in-memory or Redis). State survives across requests.
- **`@submit` handlers** work via standard form POST. The server calls the handler, re-renders the page, and returns HTML.
- **`@click`, `@input`, etc.** are silently inactive — a dev-mode console warning lists which handlers won't work.

### When to Use It

| Scenario                                        | Mode                                      |
| ----------------------------------------------- | ----------------------------------------- |
| Traditional server deployment (VPS, containers) | `interactive_server_mode=True` (default)  |
| Serverless functions (AWS Lambda, Azure, GCP)   | `stateless=True` (FaaS is request-scoped) |
| Plain Cloudflare Worker                         | `stateless=True`                          |
| Cloudflare Durable Objects                      | Default stateful WebSocket mode           |
| Horizontal scaling without Redis                | `interactive_server_mode=False`           |
| Static/content sites with forms                 | `interactive_server_mode=False`           |

### Session Configuration

In non-interactive mode, sessions use the same Redis/memory store as interactive mode. For multi-worker deployments, use Redis:

```sh
export REDIS_URL=redis://localhost:6379
```

```python
app = PyWire(interactive_server_mode=False)
# Redis detected automatically from REDIS_URL
```

With `workers=1` and the default in-memory store, sessions work without Redis — similar to a Django/Rails setup.

## Preparing for Production

1. **Build artifacts**: Run `pywire build` to compile `.wire` files into optimized Python bytecode.

   ```sh
   pywire build --optimize
   ```

2. **Environment variables**: Configure database connection strings, API keys, and other secrets via environment variables or a `.env` file.

3. **Start the server**: Use `pywire run` for a production-ready Uvicorn-based server.

   ```sh
   pywire run main:app --host 0.0.0.0 --port 8000 --workers 4
   ```

### Production Flags

| Flag              | Description                                                   |
| ----------------- | ------------------------------------------------------------- |
| `--host 0.0.0.0`  | Bind to all interfaces (required for containers)              |
| `--port 8000`     | Set the port (default: 8000)                                  |
| `--workers N`     | Number of worker processes (default: auto based on CPU cores) |
| `--no-access-log` | Disable access logging for better performance                 |

## Manual Deployment

If you prefer to write deployment configs by hand or use a platform not supported by `pywire deploy`, PyWire works with any ASGI-compatible hosting.

### Docker

Build and run locally:

```sh
docker build -t my-pywire-app .
docker run -p 8000:8000 my-pywire-app
```

### Generic ASGI Deployment

Since PyWire is a standard ASGI application, you can use any ASGI server:

```sh
# Uvicorn directly
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4

# Hypercorn
hypercorn main:app --bind 0.0.0.0:8000 --workers 4
```

## SSL / HTTPS

For development with HTTPS, use the SSL flags on `pywire dev`:

```sh
pywire dev --ssl-keyfile key.pem --ssl-certfile cert.pem
```

In production, terminate SSL at a reverse proxy (Nginx, Caddy, or your cloud provider's load balancer) rather than at the application level.

The WebSocket and long-poll endpoints refuse connections a browser opened from another site, so a page elsewhere can't act with your visitors' cookies. Browsers mark their own requests with `Sec-Fetch-Site`; for older browsers PyWire compares `Origin` with the `Host` header, or `X-Forwarded-Host` when a proxy rewrites `Host`. Clients that aren't browsers send neither and are unaffected.

Anyone can open a long-poll session or fetch an upload token, so both are bounded per process: at most 20 long-poll sessions per client address and 1,000 in all (opening one more drops the session polled longest ago, and its tab opens a new one), and each client address may stage `20 × max_upload_size` bytes an hour through `/_pywire/upload` (more gets a 429). Behind a reverse proxy, run the server with forwarded headers trusted (`uvicorn --proxy-headers`) so the client address is the visitor's.

With `debug=False` a failed event is answered with `An error occurred` on every transport; the exception, which can hold a query or a connection URL, only goes to the server log.

## Compression

PyWire gzips text responses itself: pages, the client runtime, CSS, JSON and HTTP-transport updates. The client runtime is compressed once and cached, so a cold load of a small page is about 25 KB instead of 84 KB. Images, fonts and other already-compressed files pass through untouched.

If a CDN or reverse proxy in front of the app already compresses, turn it off to save the CPU:

```python
app = PyWire(compress=False)
```

WebSocket messages use the browser's permessage-deflate, negotiated by Uvicorn. See `pywire run --no-ws-deflate` in the [CLI guide](/docs/guides/cli) for the memory trade-off.

## Static Files

PyWire automatically serves files from the `static/` directory at the `/static` URL prefix. In production, consider serving static files from a CDN or reverse proxy for better performance.
