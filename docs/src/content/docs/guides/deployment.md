---
title: Deployment
description: Deploying your PyWire application to production.
---

PyWire applications can be deployed anywhere that supports Python and ASGI (e.g., Render, Fly.io, Railway, DigitalOcean, or your own VPS).

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

To scale to multiple machines (`fly scale count N`), you need sticky sessions or a shared Redis instance — `fly redis create`, then set `REDIS_URL`. PyWire auto-detects it with no code changes needed.

### Options

| Flag         | Description                                                       |
| ------------ | ----------------------------------------------------------------- |
| `--platform` | Target platform: `docker`, `render`, or `fly` (default: `docker`) |
| `--out-dir`  | Output directory for generated files (default: `.`)               |

The command validates your project before generating configs. If `pyproject.toml` or `uv.lock` is missing, you'll see a warning.

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

## Static Files

PyWire automatically serves files from the `static/` directory at the `/static` URL prefix. In production, consider serving static files from a CDN or reverse proxy for better performance.
