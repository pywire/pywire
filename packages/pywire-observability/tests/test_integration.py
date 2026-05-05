"""Tests for ``connect_observability``."""

from __future__ import annotations

import logging
from typing import Any

from pywire_observability import RequestIDMiddleware, connect_observability


class _StubApp:
    def __init__(self) -> None:
        self.middleware: list[tuple[type, dict]] = []

    def add_middleware(self, cls: type, **kwargs: Any) -> None:
        self.middleware.append((cls, kwargs))


def _classes(app: _StubApp) -> list[type]:
    return [cls for cls, _ in app.middleware]


def test_default_install_adds_request_id_middleware() -> None:
    app = _StubApp()
    connect_observability(app)
    assert RequestIDMiddleware in _classes(app)


def test_request_id_disabled_skips_middleware() -> None:
    app = _StubApp()
    connect_observability(app, request_id=False)
    assert RequestIDMiddleware not in _classes(app)


def test_custom_inbound_headers_passed_through() -> None:
    app = _StubApp()
    connect_observability(app, inbound_headers=("x-custom-trace",))
    kwargs = next(kw for cls, kw in app.middleware if cls is RequestIDMiddleware)
    assert kwargs["inbound_headers"] == ("x-custom-trace",)


def test_custom_response_header_name() -> None:
    app = _StubApp()
    connect_observability(app, request_id_header="x-trace-id")
    kwargs = next(kw for cls, kw in app.middleware if cls is RequestIDMiddleware)
    assert kwargs["header_name"] == "x-trace-id"


def test_json_logging_off_by_default() -> None:
    app = _StubApp()
    root = logging.getLogger()
    handlers_before = list(root.handlers)
    connect_observability(app)
    assert root.handlers == handlers_before


def test_json_logging_when_enabled() -> None:
    """connect_observability(json_logging=True) installs the JSON handler."""
    import io
    import json as _json

    app = _StubApp()
    stream = io.StringIO()

    # configure_json_logging respects a custom stream — but
    # connect_observability doesn't expose that yet; we exercise the
    # plumbing via the public path (root logger) and check effects.
    root = logging.getLogger()
    saved = list(root.handlers)
    try:
        connect_observability(app, json_logging=True)
        # Replace the installed handler's stream so we can capture.
        root.handlers[0].stream = stream  # type: ignore[attr-defined]
        root.info("after-config")
        line = stream.getvalue().strip().splitlines()[-1]
        payload = _json.loads(line)
        assert payload["message"] == "after-config"
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved:
            root.addHandler(h)
