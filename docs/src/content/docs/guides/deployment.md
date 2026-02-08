---
title: Deployment
description: Deploying your PyWire application to production.
---

PyWire applications can be deployed anywhere that supports Python and ASGI (e.g., Fly.io, Railway, DigitalOcean, or your own VPS).

We are still actively working on optimizing the framework for deployment. We aim to support low-cost hobby deployments that frameworks like Astro excel at, but also support major enterprise deployments that require load balancing and where cost and efficiency come into play.

## Preparing for Production

1. **Build Artifacts**: Run `pywire build` to generate optimized artifacts. _Still WIP_
2. **Environment Variables**: Configure your database connection strings, API keys, etc.
3. **ASGI Server**: Use `pywire run` or a standard ASGI server like Uvicorn or Hypercorn.

```sh
pywire run main:app --host 0.0.0.0 --port 8000
```

## Deployment Options

Right now we support two deployment options using the `create-pywire-app` quickstart.

### Docker

We recommend using Docker for easy and portable deployment. The generated Docker image installs only the modules needed to keep the image small and the build fast.

### Fly.io

We offer a pre-configured [Fly.io](https://fly.io/) deployment template to get your app from development to production faster and with less headache.
