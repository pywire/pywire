"""Request-scoped observability primitives.

Three :class:`contextvars.ContextVar` instances that propagate identity
through the request lifecycle:

- :data:`request_id_ctx` — set once per HTTP request or once per WS
  connection lifetime. Identifies a single user-driven action chain.
- :data:`connection_id_ctx` — set once per WebSocket connection.
  Same value for every event on the connection.
- :data:`event_id_ctx` — set per WS event handler call. Lets logs
  correlate a specific click/submit within a longer connection.

Background tasks spawned via :func:`asyncio.create_task` inherit the
ContextVar values present at task-creation time (Python 3.7+ stdlib
behavior). Spawn tasks before the originating handler's ``finally``
block resets context to keep the IDs flowing into the task.

These primitives are intentionally pure stdlib — :mod:`pywire-observability`
reads them to populate JSON log records and produce request-scoped
spans, but the framework sets them with no extra dependency.
"""

from __future__ import annotations

import contextvars
from typing import Optional

request_id_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "pywire_request_id", default=None
)

connection_id_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "pywire_connection_id", default=None
)

event_id_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "pywire_event_id", default=None
)
