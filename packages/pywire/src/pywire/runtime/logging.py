import asyncio
import contextvars
import io
import logging
import sys
from typing import IO, Any, Callable, Coroutine, Iterable

from rich.text import Text

# Context variable to hold the log callback for the current request/session
# Callback signature: async def callback(message: str)
log_callback_ctx: contextvars.ContextVar[
    Callable[[str], Coroutine[Any, Any, None]] | None
] = contextvars.ContextVar("log_callback_ctx", default=None)


class ContextAwareStdout:
    """
    Simulates stdout but intercepts writes to send to specific clients
    based on the current context.
    """

    def __init__(self, original_stdout: IO[str], level: str = "info") -> None:
        self.original_stdout = original_stdout
        self.level = level
        self.buffer = io.StringIO()

    def write(self, message: str) -> None:
        # Always write to original stdout
        self.original_stdout.write(message)

        # Check context for callback
        callback = log_callback_ctx.get()
        if callback:
            # Schedule the callback. Strip ANSI via Rich's structured parser
            # so user code that prints colored output still renders cleanly
            # in the browser console.
            try:
                plain = Text.from_ansi(message).plain
            except Exception:
                plain = message
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    loop.create_task(self._safe_callback(callback, plain))
            except RuntimeError:
                # No running loop, can't stream
                pass

    def flush(self) -> None:
        self.original_stdout.flush()

    async def _safe_callback(self, callback: Callable[..., Any], message: str) -> None:
        try:
            # Check if callback accepts level argument
            import inspect

            sig = inspect.signature(callback)
            if "level" in sig.parameters:
                await callback(message, level=self.level)
            else:
                await callback(message)
        except Exception:
            pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self.original_stdout, name)


# Global installation
_installed = False


def install_logging_interceptor() -> None:
    global _installed
    if not _installed:
        sys.stdout = ContextAwareStdout(sys.stdout, level="info")
        # Handle stderr too? Usually yes for errors.
        sys.stderr = ContextAwareStdout(sys.stderr, level="error")
        _installed = True


_LEVEL_NAME_MAP = {
    logging.DEBUG: "debug",
    logging.INFO: "info",
    logging.WARNING: "warn",
    logging.ERROR: "error",
    logging.CRITICAL: "error",
}


class BrowserLogForwarder(logging.Handler):
    """Forwards structured LogRecords to the browser via log_callback_ctx.

    Uses record.getMessage() (no ANSI) and strips Rich markup tokens via
    Text.from_markup, so the browser receives plain text regardless of how
    the parent handler renders to the terminal.
    """

    def emit(self, record: logging.LogRecord) -> None:
        callback = log_callback_ctx.get()
        if callback is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if not loop.is_running():
            return
        try:
            raw = record.getMessage()
            try:
                plain = Text.from_markup(raw).plain
            except Exception:
                plain = raw
            level = _LEVEL_NAME_MAP.get(record.levelno, "info")
            loop.create_task(_forward_to_callback(callback, plain, level))
        except Exception:
            self.handleError(record)


async def _forward_to_callback(
    callback: Callable[..., Any], message: str, level: str
) -> None:
    try:
        import inspect

        sig = inspect.signature(callback)
        if "level" in sig.parameters:
            await callback(message, level=level)
        else:
            await callback(message)
    except Exception:
        pass


def install_browser_log_forwarder(logger_names: Iterable[str]) -> BrowserLogForwarder:
    """Attach a BrowserLogForwarder to each named logger (deduped)."""
    handler = BrowserLogForwarder()
    handler.setLevel(logging.DEBUG)
    for name in logger_names:
        lg = logging.getLogger(name) if name else logging.getLogger()
        if not any(isinstance(h, BrowserLogForwarder) for h in lg.handlers):
            lg.addHandler(handler)
    return handler
