"""Tests for the JSON log formatter."""

from __future__ import annotations

import io
import json
import logging

import pytest

from pywire_observability.logging import JSONFormatter, configure_json_logging


def _format_record(**record_kwargs) -> dict:
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name=record_kwargs.pop("name", "test"),
        level=record_kwargs.pop("level", logging.INFO),
        pathname=record_kwargs.pop("pathname", "/tmp/x.py"),
        lineno=record_kwargs.pop("lineno", 1),
        msg=record_kwargs.pop("msg", "hello"),
        args=record_kwargs.pop("args", ()),
        exc_info=record_kwargs.pop("exc_info", None),
    )
    for key, value in record_kwargs.items():
        setattr(record, key, value)
    return json.loads(formatter.format(record))


def test_basic_record_has_core_fields() -> None:
    out = _format_record()
    assert out["level"] == "INFO"
    assert out["logger"] == "test"
    assert out["message"] == "hello"
    assert "timestamp" in out
    assert out["timestamp"].endswith("+00:00")  # UTC ISO8601


def test_message_args_are_interpolated() -> None:
    out = _format_record(msg="user=%s", args=("alice",))
    assert out["message"] == "user=alice"


def test_extra_fields_included() -> None:
    out = _format_record(handler="on_click", path="/page")
    assert out["handler"] == "on_click"
    assert out["path"] == "/page"


def test_reserved_attrs_not_leaked() -> None:
    """Internal LogRecord attrs (pathname, lineno, etc.) must not appear
    as JSON fields — they're noise for log aggregators."""
    out = _format_record()
    for key in ("pathname", "lineno", "filename", "funcName", "module"):
        assert key not in out


def test_exception_field_when_exc_info_present() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        out = _format_record(exc_info=sys.exc_info())
    assert "exception" in out
    assert "ValueError" in out["exception"]
    assert "boom" in out["exception"]


def test_non_serialisable_extra_falls_back_safely() -> None:
    """A bad ``extra=`` shouldn't break logging — formatter falls back."""

    class Unserialisable:
        def __repr__(self) -> str:
            return "<U>"

    out = _format_record(weird=Unserialisable())
    # _coerce uses repr for unknowns; the record still serialises.
    assert out["weird"] == "<U>"


def test_static_fields_merged() -> None:
    formatter = JSONFormatter(static_fields={"service": "demo", "env": "test"})
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname="/x.py",
        lineno=1,
        msg="hi",
        args=(),
        exc_info=None,
    )
    out = json.loads(formatter.format(record))
    assert out["service"] == "demo"
    assert out["env"] == "test"


def test_context_vars_pulled_when_set() -> None:
    """When the framework's context vars are set, they appear in the
    record automatically — no per-record extra= needed."""
    from pywire.runtime.observability import (
        connection_id_ctx,
        event_id_ctx,
        request_id_ctx,
    )

    rid_token = request_id_ctx.set("rid-123")
    cid_token = connection_id_ctx.set("cid-456")
    eid_token = event_id_ctx.set("eid-789")
    try:
        out = _format_record()
    finally:
        request_id_ctx.reset(rid_token)
        connection_id_ctx.reset(cid_token)
        event_id_ctx.reset(eid_token)
    assert out["request_id"] == "rid-123"
    assert out["connection_id"] == "cid-456"
    assert out["event_id"] == "eid-789"


def test_unset_context_vars_omitted() -> None:
    out = _format_record()
    assert "request_id" not in out
    assert "connection_id" not in out
    assert "event_id" not in out


def test_configure_json_logging_replaces_handlers() -> None:
    stream = io.StringIO()
    handler = configure_json_logging(stream=stream)
    try:
        logging.getLogger().info("test message", extra={"key": "value"})
    finally:
        logging.getLogger().removeHandler(handler)

    line = stream.getvalue().strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["message"] == "test message"
    assert payload["key"] == "value"


def test_configure_json_logging_idempotent() -> None:
    stream1 = io.StringIO()
    stream2 = io.StringIO()
    h1 = configure_json_logging(stream=stream1)
    h2 = configure_json_logging(stream=stream2)
    try:
        logging.getLogger().info("only stream2 should see this")
    finally:
        logging.getLogger().removeHandler(h2)

    assert stream1.getvalue() == ""
    assert "only stream2" in stream2.getvalue()
    assert h1 is not h2


@pytest.mark.parametrize(
    "level_no,level_name",
    [
        (logging.DEBUG, "DEBUG"),
        (logging.WARNING, "WARNING"),
        (logging.ERROR, "ERROR"),
    ],
)
def test_levels_serialised(level_no: int, level_name: str) -> None:
    out = _format_record(level=level_no)
    assert out["level"] == level_name


def test_cyclic_extra_does_not_crash_logging() -> None:
    """A cyclic extra= dict would recurse forever in _coerce without
    the depth guard. Confirm the formatter degrades cleanly to repr
    instead of raising RecursionError."""
    cycle: dict = {}
    cycle["self"] = cycle
    out = _format_record(weird=cycle)
    # Formatter must produce SOMETHING — either a depth-limited
    # representation under the field, or the fallback degraded record.
    # Either way, it didn't raise.
    assert "level" in out


def test_configure_json_logging_warns_on_foreign_handlers() -> None:
    import io
    import warnings

    root = logging.getLogger()
    saved = list(root.handlers)
    foreign = logging.StreamHandler(io.StringIO())
    root.addHandler(foreign)
    try:
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            configure_json_logging(stream=io.StringIO())
        assert any(
            "removed" in str(w.message) and "handler" in str(w.message)
            for w in recorded
        )
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved:
            root.addHandler(h)


def test_configure_json_logging_does_not_warn_on_replace_self() -> None:
    """Re-configuring after a previous configure_json_logging call must
    not warn — the marker on our own handler tells us we're replacing
    a pywire-installed handler, not a foreign one."""
    import io
    import warnings

    root = logging.getLogger()
    saved = list(root.handlers)
    try:
        # Clean slate.
        for h in list(root.handlers):
            root.removeHandler(h)
        configure_json_logging(stream=io.StringIO())
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            configure_json_logging(stream=io.StringIO())
        assert not any("removed" in str(w.message) for w in recorded)
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved:
            root.addHandler(h)
