"""API for interacting with the host shell in local-first apps."""

from typing import Optional
from starlette.requests import Request
import contextvars

# Context variable to hold the current request, allowing us to find the shell instance
_request_ctx: contextvars.ContextVar[Optional[Request]] = contextvars.ContextVar(
    "_request_ctx", default=None
)


class WindowProxy:
    """Proxy for controlling the shell window."""

    @property
    def _shell(self):
        request = _request_ctx.get()
        if not request:
            raise RuntimeError(
                "Shell API can only be used within a request context (wire component or route handler)"
            )

        shell = getattr(request.app.state, "shell", None)
        if not shell:
            raise RuntimeError("Application is not running within a PyWire Shell")
        return shell

    def set_title(self, title: str):
        """Set the window title."""
        self._shell.set_title(title)

    def resize(self, width: int, height: int):
        """Resize the window."""
        self._shell.resize(width, height)

    def execute_javascript(self, script: str):
        """Execute JavaScript in the window."""
        self._shell.execute_javascript(script)


# Singleton proxy instance
window = WindowProxy()
