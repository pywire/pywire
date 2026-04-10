from starlette.middleware.base import BaseHTTPMiddleware

from pywire.runtime.app import PyWire


class E2ETestMiddleware(BaseHTTPMiddleware):
    """Middleware that adds a test header — used to verify middleware works e2e."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-E2E-Middleware"] = "active"
        return response


app = PyWire("./pages", debug=True, middleware=[E2ETestMiddleware])
