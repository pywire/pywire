import asyncio
import io
from unittest.mock import MagicMock

import pytest
from pywire.runtime.logging import ContextAwareStdout, log_callback_ctx


def test_context_aware_stdout_no_context() -> None:
    """Verify print goes to original stdout when no context is active."""
    original_stdout = io.StringIO()
    ca_stdout = ContextAwareStdout(original_stdout)

    ca_stdout.write("Hello World")
    assert original_stdout.getvalue() == "Hello World"


@pytest.mark.asyncio
async def test_context_aware_stdout_with_context() -> None:
    """Verify print is intercepted when context is active."""
    original_stdout = io.StringIO()
    ca_stdout = ContextAwareStdout(original_stdout)

    received_msgs = []

    async def callback(msg: str) -> None:
        received_msgs.append(msg)

    token = log_callback_ctx.set(callback)
    try:
        ca_stdout.write("Intercepted message\n")
        # Give the loop a chance to run the scheduled task
        await asyncio.sleep(0.01)

        assert "Intercepted message" in original_stdout.getvalue()
        assert received_msgs == ["Intercepted message\n"]
    finally:
        log_callback_ctx.reset(token)


@pytest.mark.asyncio
async def test_websocket_logging_integration() -> None:
    """Verify websocket handler logic for logging."""
    from pywire.runtime.websocket import WebSocketHandler

    # Mock websocket
    websocket = MagicMock()
    # Mock send_bytes as async
    websocket.send_bytes = MagicMock(return_value=asyncio.Future())
    websocket.send_bytes.return_value.set_result(None)

    handler = WebSocketHandler(None)

    # The handler defines send_log locally in _handle_event.
    # Let's verify _send_console_message instead as it's the core.
    await handler._send_console_message(websocket, output="Test log")

    assert websocket.send_bytes.called
    # Check that it sent something via msgpack
    args, kwargs = websocket.send_bytes.call_args
    import msgpack

    sent_data = msgpack.unpackb(args[0], raw=False)
    assert sent_data["type"] == "console"
    assert sent_data["lines"] == ["Test log"]
