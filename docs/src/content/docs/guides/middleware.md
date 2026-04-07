---
title: Middleware
description: Adding ASGI middleware to your PyWire application.
---

PyWire supports standard ASGI middleware natively. Middleware wraps the application and can process requests before they reach your handlers and modify responses on the way out. Common uses include authentication, CORS, logging, and session management.

## Adding Middleware

### Via Constructor

Pass a list of middleware classes to the `middleware` parameter:

```python
from pywire import PyWire
from starlette.middleware.cors import CORSMiddleware

app = PyWire(
    middleware=[CORSMiddleware],
)
```

To pass options to a middleware class, use a tuple of `(class, options_dict)`:

```python
app = PyWire(
    middleware=[
        (CORSMiddleware, {
            "allow_origins": ["https://example.com"],
            "allow_methods": ["*"],
        }),
    ],
)
```

### Via `add_middleware()`

You can also add middleware after construction:

```python
app = PyWire()
app.add_middleware(CORSMiddleware, allow_origins=["*"])
```

## Middleware Ordering

The first middleware in the list is the **outermost** — it processes the request first and the response last. This matches the convention used by Starlette and other ASGI frameworks.

```python
app = PyWire(
    middleware=[
        LoggingMiddleware,   # Runs first on request, last on response
        AuthMiddleware,      # Runs second on request, second-to-last on response
    ],
)
```

## Writing Custom Middleware

PyWire supports any ASGI middleware. The simplest approach is to use Starlette's `BaseHTTPMiddleware`:

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        import time
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        response.headers["X-Response-Time"] = f"{duration:.3f}s"
        return response
```

For full control, write a raw ASGI middleware:

```python
class SimpleAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            token = headers.get(b"authorization", b"").decode()
            if not token.startswith("Bearer "):
                from starlette.responses import JSONResponse
                response = JSONResponse({"error": "Unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
```

## Example: Authentication

A common pattern is an authentication middleware that reads a session or token and makes user info available via a context variable:

```python
from contextvars import ContextVar
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        session = request.session
        token = current_user_id.set(session.get("user_id"))
        try:
            return await call_next(request)
        finally:
            current_user_id.reset(token)

app = PyWire(
    middleware=[
        AuthMiddleware,
        (SessionMiddleware, {"secret_key": "your-secret-key"}),
    ],
)
```

## Transport Compatibility

- **HTTP requests**: Pass through all middleware.
- **WebSocket connections**: Pass through middleware (Starlette's `BaseHTTPMiddleware` forwards WebSocket scopes automatically).
- **WebTransport connections**: Bypass middleware entirely. WebTransport is handled directly by the PyWire transport layer.

## Available Middleware

Since PyWire is built on Starlette, you can use any Starlette-compatible middleware:

- `starlette.middleware.cors.CORSMiddleware` — Cross-origin resource sharing
- `starlette.middleware.sessions.SessionMiddleware` — Cookie-based sessions
- `starlette.middleware.trustedhost.TrustedHostMiddleware` — Host header validation
- `starlette.middleware.httpsredirect.HTTPSRedirectMiddleware` — HTTP to HTTPS redirect
- `starlette.middleware.gzip.GZipMiddleware` — Response compression
