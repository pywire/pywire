"""JSON log formatter for PyWire apps.

A single-record-per-line JSON formatter that pulls request-scoped
context (request_id, connection_id, event_id) from the framework's
ContextVars when present. Compatible with Datadog, ELK, Loki,
CloudWatch, Cloud Logging, and Azure Monitor — all of which auto-parse
JSON-per-line stdout.

Activate via :func:`configure_json_logging` or the CLI flag
``pywire run --log-format=json`` / ``pywire dev --log-format=json``.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import sys
import traceback
from typing import Any, Optional


# These keys come from logging.LogRecord and are always present;
# excluding them from the "extra fields" pass keeps the output schema
# clean. ``getMessage`` covers ``msg`` + ``args``.
_RESERVED_RECORD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


class JSONFormatter(logging.Formatter):
    """Emit each log record as a single line of JSON.

    Output schema::

        {
          "timestamp": "2026-05-05T14:32:01.234567+00:00",
          "level": "INFO",
          "logger": "pywire.runtime.app",
          "message": "Page rendered",
          "request_id": "...",         # when set
          "connection_id": "...",       # when set on WS scopes
          "event_id": "...",            # when set inside an event handler
          "exception": "Traceback...",  # when exc_info is present
          "extra_user_field": "..."     # arbitrary keys from logger.info(..., extra={...})
        }
    """

    def __init__(
        self,
        *,
        include_context: bool = True,
        static_fields: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__()
        self._include_context = include_context
        self._static_fields = dict(static_fields or {})

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": _format_timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if self._static_fields:
            payload.update(self._static_fields)

        if self._include_context:
            ctx = _read_context()
            if ctx:
                payload.update(ctx)

        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRS or key.startswith("_"):
                continue
            if key in payload:
                continue
            payload[key] = _coerce(value)

        if record.exc_info:
            payload["exception"] = "".join(traceback.format_exception(*record.exc_info))
        elif record.exc_text:
            payload["exception"] = record.exc_text
        if record.stack_info:
            payload["stack"] = record.stack_info

        try:
            return json.dumps(payload, default=_coerce, separators=(",", ":"))
        except (TypeError, ValueError):
            # Fall back to a degraded record so a bad ``extra=`` dict
            # never breaks logging itself.
            return json.dumps(
                {
                    "timestamp": payload["timestamp"],
                    "level": payload["level"],
                    "logger": payload["logger"],
                    "message": payload["message"],
                    "_format_error": "non-serialisable extra fields dropped",
                },
                separators=(",", ":"),
            )


def _format_timestamp(record: logging.LogRecord) -> str:
    return _dt.datetime.fromtimestamp(record.created, tz=_dt.timezone.utc).isoformat()


def _read_context() -> dict[str, str]:
    """Return whichever of request_id/connection_id/event_id are set.

    The ContextVars live in :mod:`pywire.runtime.observability`. Fail
    silently if pywire isn't importable or the module hasn't shipped
    yet — the formatter still works as a generic JSON logger.
    """
    try:
        from pywire.runtime.observability import (
            connection_id_ctx,
            event_id_ctx,
            request_id_ctx,
        )
    except ImportError:
        return {}

    out: dict[str, str] = {}
    rid = request_id_ctx.get()
    if rid:
        out["request_id"] = rid
    cid = connection_id_ctx.get()
    if cid:
        out["connection_id"] = cid
    eid = event_id_ctx.get()
    if eid:
        out["event_id"] = eid
    return out


def _coerce(value: Any) -> Any:
    """Best-effort conversion of non-JSON-native values to strings."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_coerce(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _coerce(v) for k, v in value.items()}
    return repr(value)


def configure_json_logging(
    *,
    level: int = logging.INFO,
    stream: Any = None,
    static_fields: Optional[dict[str, Any]] = None,
) -> logging.Handler:
    """Install :class:`JSONFormatter` on the root logger.

    Removes any existing handlers and replaces them with a single
    StreamHandler writing to stderr (default) so log line ordering is
    deterministic. Returns the installed handler so callers can adjust
    afterwards.

    Idempotent — calling twice replaces the previous handler.
    """
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JSONFormatter(static_fields=static_fields))
    handler.setLevel(level)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    return handler
