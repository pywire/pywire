# pywire-observability

Request-ID propagation, JSON logging, OpenTelemetry, and Sentry recipes for PyWire apps.

## Install

```sh
pip install pywire-observability
```

## Quick start

```python
from pywire import PyWire
from pywire_observability import connect_observability

app = PyWire(...)
connect_observability(app, json_logging=True)
```

That's the full prod-ready loadout: request IDs propagate across HTTP and WebSocket scopes, every log line emits as JSON with the request/connection/event ID auto-attached, and HTTP-500s + WebSocket handler exceptions flow through the standard `pywire.*` logger hierarchy (so they reach any aggregator that consumes Python's `logging`).

## What ships

### Request-ID propagation

`RequestIDMiddleware` reads inbound trace headers in priority order:

1. `traceparent` (W3C Trace Context — the trace_id portion is preserved so OTel-aware backends auto-correlate logs to traces)
2. `x-request-id`
3. `x-correlation-id`
4. Fresh `uuid4().hex` if none present

The id is written to `scope["pywire_request_id"]` and the `request_id_ctx` ContextVar in `pywire.runtime.observability` for the duration of the request — log records emitted from anywhere in the request path (handlers, background tasks, render callbacks) automatically carry it. HTTP responses echo it back as `X-Request-ID` so downstream services can correlate.

WebSocket connections get an extra `connection_id` (one per socket lifetime) and `event_id` (one per event handler call) so logs can correlate by socket, by single user action, or by both.

### JSON logging

`configure_json_logging()` (or `connect_observability(json_logging=True)`) replaces the root logger's handlers with a single `JSONFormatter` writing one JSON record per line:

```json
{"timestamp": "2026-05-05T14:32:01.234567+00:00", "level": "INFO", "logger": "pywire.runtime.app", "message": "Page rendered", "request_id": "...", "connection_id": "...", "event_id": "..."}
```

Compatible with Datadog, ELK, Loki, CloudWatch, Cloud Logging, and Azure Monitor — all auto-parse JSON-per-line stdout.

Activate via:
- `connect_observability(app, json_logging=True)` programmatically
- `PYWIRE_LOG_FORMAT=json` env var (when using `pywire-cli`)
- `pywire run --log-format=json` / `pywire dev --log-format=json` CLI flag

### OpenTelemetry recipe

```sh
pip install opentelemetry-api opentelemetry-sdk \
            opentelemetry-instrumentation-starlette \
            opentelemetry-exporter-otlp
```

```python
from pywire_observability.otel import instrument

instrument(app)
```

Wires the standard Starlette ASGI instrumentation onto PyWire's inner Starlette app. HTTP requests + WebSocket upgrade handshakes are auto-spanned. Per-WS-event spans are not yet covered (see [#254](https://github.com/pywire/pywire/issues/254)). Internal ASGI replays are filtered out so the trace tree stays clean.

### Sentry recipe

```sh
pip install 'sentry-sdk[starlette]'
```

```python
from pywire_observability.sentry import init as init_sentry

init_sentry(dsn=os.environ["SENTRY_DSN"], environment="prod")
```

Wires Sentry's `LoggingIntegration` (captures every `logger.exception(...)` — including the WS / HTTP-500 fixes pywire-observability ships) and `StarletteIntegration` (HTTP request context). Every captured event is auto-tagged with `pywire_request_id`, `pywire_connection_id`, and `pywire_event_id` when present.

## What this fixes

PyWire core previously logged WS handler exceptions with `print` + `traceback.print_exc()` — invisible to any logging-based aggregator (Sentry's `LoggingIntegration`, ELK forwarders, etc.). HTTP 500s were swallowed into the error page with no log call. Both paths now use `logger.exception(...)` so production failures reach observability infrastructure.

## Configuration via environment

| Variable | Default | Effect |
|---|---|---|
| `PYWIRE_LOG_FORMAT` | `text` | Set to `json` to activate JSON logging via the CLI flag default. |
| `PYWIRE_LOG_LEVEL` | `WARNING` | Sets the level on the `pywire` logger (existing PyWire core var). |

## Deferred to v0.2

- Per-WebSocket-event OTel spans — [#254](https://github.com/pywire/pywire/issues/254)
- Metrics surface (Prometheus / OTel meter) — [#255](https://github.com/pywire/pywire/issues/255)
- Distributed-tracing-aware page state snapshots — [#256](https://github.com/pywire/pywire/issues/256)
- Bundled OTel/Sentry extras — [#257](https://github.com/pywire/pywire/issues/257)
