"""Sentry integration recipe.

PyWire does not bundle ``sentry-sdk``. Install it yourself::

    pip install 'sentry-sdk[starlette]'

Then call :func:`init` once at startup::

    from pywire_observability.sentry import init as init_sentry

    init_sentry(dsn=os.environ["SENTRY_DSN"], environment=\"prod\")

This wires:

- Sentry's ``LoggingIntegration`` capturing all ``logger.exception(...)``
  calls — including the WS / HTTP-500 fixes pywire-observability ships.
- Sentry's ``StarletteIntegration`` for HTTP request context.
- Tags every captured event with ``pywire_request_id``,
  ``pywire_connection_id``, and ``pywire_event_id`` when present so
  Sentry issues are searchable by the same IDs that appear in JSON logs.

For more advanced setups (custom transports, before-send filters,
performance sampling), call ``sentry_sdk.init(...)`` directly with
your own kwargs.
"""

from __future__ import annotations

from typing import Any, Optional


def init(
    *,
    dsn: str,
    environment: Optional[str] = None,
    release: Optional[str] = None,
    traces_sample_rate: float = 0.0,
    sample_rate: float = 1.0,
    **extra_kwargs: Any,
) -> None:
    """Initialize ``sentry-sdk`` with PyWire-aware defaults.

    Args mirror the most common ``sentry_sdk.init`` kwargs. Pass any
    additional ``sentry_sdk.init`` kwargs through ``extra_kwargs``.
    """
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "pywire_observability.sentry.init requires sentry-sdk. "
            "Install with: pip install 'sentry-sdk[starlette]'"
        ) from exc

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        traces_sample_rate=traces_sample_rate,
        sample_rate=sample_rate,
        integrations=[
            LoggingIntegration(),
            StarletteIntegration(),
        ],
        before_send=_attach_pywire_tags,
        **extra_kwargs,
    )


def _attach_pywire_tags(event: dict, hint: dict) -> dict:
    """Tag every Sentry event with current PyWire request/connection/event IDs.

    Reads from :mod:`pywire.runtime.observability` ContextVars. When
    the framework hasn't set them (e.g. background work outside any
    request), the tags are simply absent.
    """
    try:
        from pywire.runtime.observability import (
            connection_id_ctx,
            event_id_ctx,
            request_id_ctx,
        )
    except ImportError:
        return event

    tags = event.setdefault("tags", {})
    rid = request_id_ctx.get()
    if rid:
        tags["pywire_request_id"] = rid
    cid = connection_id_ctx.get()
    if cid:
        tags["pywire_connection_id"] = cid
    eid = event_id_ctx.get()
    if eid:
        tags["pywire_event_id"] = eid
    return event
