import pytest
from unittest.mock import AsyncMock, Mock, patch
from pywire.runtime.page import BasePage
from pywire.core.refs import ref, InputElement


class MockWebSocket:
    def __init__(self):
        self.sent_messages = []
        self.scope = {"type": "websocket"}
        self.accepted = False
        self.closed = False

    async def send_bytes(self, data):
        self.sent_messages.append(data)

    async def accept(self):
        self.accepted = True

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_ref_sync_server_side():
    """Test that server handles ref_sync messages correctly."""
    from pywire.runtime.websocket import WebSocketHandler

    app = Mock()
    handler = WebSocketHandler(app)
    ws = MockWebSocket()

    # Setup page with a ref
    page = BasePage(request=Mock(), params={}, query={}, path={}, url=None)
    my_ref = ref[InputElement]()
    # Bind ref (usually done by generator/loader but we simulate it)
    my_ref._ref_id = "ref-123"
    my_ref._bound_type = "input"
    page._refs_by_id["ref-123"] = my_ref

    handler.connection_pages[ws] = page

    # Send sync message
    data = {"type": "ref_sync", "refId": "ref-123", "value": "test_value"}
    await handler._handle_ref_sync(ws, data)

    assert my_ref.value == "test_value"


@pytest.mark.asyncio
async def test_command_forwarding_in_render_update():
    """Test that commands are collected and sent during render_update."""
    page = BasePage(request=Mock(), params={}, query={}, path={}, url=None)

    # Create ref and queue command
    my_ref = ref[InputElement]()
    my_ref._ref_id = "ref-1"
    my_ref._bound_type = "input"
    page._refs_by_id["ref-1"] = my_ref

    # Queue a focus command *before* render
    my_ref.focus()

    # Mock render to return simple HTML (since we don't have real templates here)
    with patch.object(page, "render", new_callable=AsyncMock) as mock_render:
        mock_render.return_value = Mock(body=b"<html></html>")

        # Test full update
        update = await page.render_update(init=False)

        assert update["type"] == "full"
        assert "commands" in update
        assert len(update["commands"]) == 1
        assert update["commands"][0]["cmd"] == "focus"
        assert update["commands"][0]["refId"] == "ref-1"


@pytest.mark.asyncio
async def test_command_forwarding_in_websocket_payload():
    """Test that _send_update_payload includes commands."""
    from pywire.runtime.websocket import WebSocketHandler
    import msgpack

    app = Mock()
    handler = WebSocketHandler(app)
    ws = MockWebSocket()

    # Test Full Update with commands
    update_full = {
        "type": "full",
        "html": "<div></div>",
        "commands": [{"cmd": "focus", "refId": "r1"}],
    }

    await handler._send_update_payload(ws, update_full)

    assert len(ws.sent_messages) == 1
    decoded = msgpack.unpackb(ws.sent_messages[0])
    assert decoded["type"] == "update"
    assert decoded["html"] == "<div></div>"
    assert "commands" in decoded
    assert decoded["commands"][0]["cmd"] == "focus"

    # Test Region Update with commands
    ws.sent_messages.clear()
    update_regions = {
        "type": "regions",
        "regions": [],
        "commands": [{"cmd": "blur", "refId": "r2"}],
    }

    await handler._send_update_payload(ws, update_regions)

    assert len(ws.sent_messages) == 1
    decoded_regions = msgpack.unpackb(ws.sent_messages[0])
    assert "commands" in decoded_regions
    assert decoded_regions["commands"][0]["cmd"] == "blur"
