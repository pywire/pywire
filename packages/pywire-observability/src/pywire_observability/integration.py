"""Single integration entry point — ``connect_observability(app, ...)``.

Wires :class:`RequestIDMiddleware` onto a PyWire app and (optionally)
swaps the root logger's formatter for :class:`JSONFormatter`. Errors
from the framework's WS / HTTP-500 paths flow through the standard
``pywire.*`` loggers (fixed in core), so installing the JSON formatter
also captures those.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

from pywire_observability.logging import configure_json_logging
from pywire_observability.middleware import RequestIDMiddleware


def connect_observability(
    app: Any,
    *,
    request_id: bool = True,
    request_id_header: str = "x-request-id",
    inbound_headers: Optional[Sequence[str]] = None,
    json_logging: bool = False,
    log_level: int = logging.INFO,
    static_log_fields: Optional[dict[str, Any]] = None,
) -> None:
    """Attach observability middleware to a PyWire app.

    Args:
        app: The :class:`pywire.PyWire` instance.
        request_id: Install :class:`RequestIDMiddleware`. Default on.
        request_id_header: Outbound header name to echo the id under
            (case-insensitive). Default ``X-Request-ID``.
        inbound_headers: Override the inbound header priority list.
            Defaults to ``traceparent``, ``x-request-id``,
            ``x-correlation-id``.
        json_logging: Replace the root logger's handlers with a single
            :class:`JSONFormatter` handler. Idempotent. Off by default;
            also activatable via ``PYWIRE_LOG_FORMAT=json`` env or
            ``pywire run --log-format=json`` CLI flag.
        log_level: Level applied to the root logger when JSON logging is
            enabled.
        static_log_fields: Extra keys merged into every JSON record
            (e.g. ``{\"service\": \"my-app\", \"env\": \"prod\"}``).
    """
    if request_id:
        kwargs: dict[str, Any] = {"header_name": request_id_header}
        if inbound_headers is not None:
            kwargs["inbound_headers"] = tuple(inbound_headers)
        app.add_middleware(RequestIDMiddleware, **kwargs)

    if json_logging:
        configure_json_logging(level=log_level, static_fields=static_log_fields)
