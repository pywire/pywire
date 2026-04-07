---
title: Deployment
description: Deploying your PyWire application to production.
---

PyWire applications can be deployed anywhere that supports Python and ASGI (e.g., Fly.io, Railway, DigitalOcean, or your own VPS).

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

## Deployment Options

The `create-pywire-app` scaffolding tool can generate deployment configurations for you.

### Docker

Docker is the recommended deployment method. When you scaffold a project with `create-pywire-app`, you can choose to include a Dockerfile. The generated image:

- Uses a multi-stage build to keep the image small
- Installs only production dependencies
- Runs the app with `pywire run`

Build and run locally:

```sh
docker build -t my-pywire-app .
docker run -p 8000:8000 my-pywire-app
```

### Fly.io

PyWire offers a pre-configured [Fly.io](https://fly.io/) deployment template. If you selected the Fly.io option during `create-pywire-app`, your project includes a `fly.toml` file ready to deploy:

```sh
fly launch
fly deploy
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
