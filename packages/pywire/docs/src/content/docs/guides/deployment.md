---
title: Deployment
description: Deploying your PyWire application to production.
---

PyWire applications can be deployed anywhere that supports Python and ASGI (e.g., Fly.io, Railway, DigitalOcean, or your own VPS).

## Preparing for Production

1. **Build Artifacts**: Run `pywire build` to generate optimized artifacts.
2. **Environment Variables**: Configure your database connection strings, API keys, etc.
3. **ASGI Server**: Use `pywire run` or a standard ASGI server like Uvicorn or Hypercorn.

```bash
pywire run main:app --host 0.0.0.0 --port 8000
```

## Docker

We recommend using Docker for easy deployment. See our [Docker Guide] for a sample Dockerfile.
