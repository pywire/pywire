---
title: Edge & serverless deployment
description: Choose the PyWire deployment tier that matches your platform and timeline needs.
---

PyWire has two deployment tiers. **Stateful** keeps page instances and a server/client push channel. **Stateless** keeps no page instance between events: every POST restores a signed snapshot, dispatches one handler, renders dirty regions, and returns a new snapshot.

Choose the tier by who owns the timeline:

- Use **stateful** for server-pushed work such as `{$await}`, `push_state()`, or per-token chat/streaming.
- Use **stateless** when bounded request/response events are enough. Polling and optimistic UI make this practical without a persistent server timeline.

`PyWire(stateless=True)` is a build-time ceiling assertion. `pywire build` rejects page closures that use `{$await}` or a statically visible `push_state()` call. See [Stateless mode](/guides/stateless-mode/) and the [tier feature matrix](/guides/tier-capabilities/).

## Deployment support matrix

| Host                                         | Stateful         | Stateless | Timeline owner / ideology                                       |
| -------------------------------------------- | ---------------- | --------- | --------------------------------------------------------------- |
| Docker                                       | Yes              | Yes       | Stateful: server pushes; stateless: request-scoped              |
| Fly.io                                       | Yes              | Yes       | Stateful: server pushes; stateless: request-scoped              |
| Render                                       | Yes              | Yes       | Stateful: server pushes; stateless: request-scoped              |
| Railway                                      | Yes              | Yes       | Stateful: server pushes; stateless: request-scoped              |
| Google Cloud Run                             | Yes              | Yes       | Stateful: server pushes; stateless: request-scoped              |
| Cloudflare Durable Objects                   | Yes, at the edge | No        | The Durable Object owns a persistent session and pushes updates |
| Cloudflare plain Workers (`cloudflare-edge`) | No               | Yes       | Each request owns its event; the client carries the timeline    |
| AWS Lambda                                   | No               | Yes       | Request-scoped                                                  |
| Azure Functions                              | No               | Yes       | Request-scoped                                                  |
| GCP Cloud Functions                          | No               | Yes       | Request-scoped                                                  |

Container and long-running platforms can host either tier. FaaS/one-shot targets are stateless because they do not retain a page between invocations. The Cloudflare Durable Object target is the stateful edge alternative.

## Measured reality

In the real Cloudflare `workerd` + Pyodide gate, the counter action round-trip was **p50 ≈ 2.65 ms**, the counter snapshot was **232 B**, a 1000-row keyed-list toggle was **251 B**, and Pyodide cold start was **≈ 79 ms**. These are measured-in-workerd observations, not service promises.

AWS Lambda, Azure Functions, and GCP Cloud Functions run **native CPython**, not Pyodide. Do not apply the Cloudflare cold-start framing to them.

## Start stateless

```python
from pywire import PyWire

app = PyWire(stateless=True)  # reads PYWIRE_SECRET_KEY
```

A signing secret is mandatory. `PyWire(stateless=True)` refuses to start without `secret_key=` or `PYWIRE_SECRET_KEY`; PyWire never generates one implicitly.

For provider-specific commands and secret setup, see [Provider quickstarts](/guides/stateless-provider-quickstarts/).
