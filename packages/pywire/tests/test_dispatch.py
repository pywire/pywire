import pytest
from unittest.mock import AsyncMock, Mock, patch

from pywire.core.dispatch import dispatch, _page_context
from pywire.core.wire import _render_context
from pywire.core.refs import ref, InputElement
from pywire.runtime.page import BasePage


def _make_page() -> BasePage:
    return BasePage(request=Mock(), params={}, query={}, path={}, url=None)


def test_dispatch_queues_basic_command():
    """dispatch('my-event') queues a dispatch command with defaults."""
    page = _make_page()
    token = _render_context.set((page, None))
    try:
        dispatch("my-event")
    finally:
        _render_context.reset(token)

    assert len(page._pending_dispatches) == 1
    cmd = page._pending_dispatches[0]
    assert cmd["cmd"] == "dispatch"
    assert cmd["event"] == "my-event"
    assert cmd["detail"] is None
    assert cmd["bubbles"] is True
    assert cmd["refId"] is None


def test_dispatch_with_detail():
    """dispatch('my-event', detail={'id': 42}) includes detail."""
    page = _make_page()
    token = _render_context.set((page, None))
    try:
        dispatch("my-event", detail={"id": 42})
    finally:
        _render_context.reset(token)

    assert len(page._pending_dispatches) == 1
    cmd = page._pending_dispatches[0]
    assert cmd["detail"] == {"id": 42}


def test_dispatch_with_target_ref():
    """dispatch('my-event', target_ref=some_ref) includes refId."""
    page = _make_page()
    my_ref = ref[InputElement]()
    my_ref._ref_id = "ref-abc"
    my_ref._bound_type = "input"
    page._refs_by_id["ref-abc"] = my_ref

    token = _render_context.set((page, None))
    try:
        dispatch("my-event", target_ref=my_ref)
    finally:
        _render_context.reset(token)

    assert len(page._pending_dispatches) == 1
    cmd = page._pending_dispatches[0]
    assert cmd["refId"] == "ref-abc"


def test_dispatch_bubbles_false():
    """dispatch('my-event', bubbles=False) sets bubbles to False."""
    page = _make_page()
    token = _render_context.set((page, None))
    try:
        dispatch("my-event", bubbles=False)
    finally:
        _render_context.reset(token)

    cmd = page._pending_dispatches[0]
    assert cmd["bubbles"] is False


def test_dispatch_outside_render_context_raises():
    """dispatch() raises RuntimeError when called outside render/handler context."""
    with pytest.raises(RuntimeError, match="must be called during"):
        dispatch("my-event")


@pytest.mark.asyncio
async def test_dispatch_commands_collected():
    """Dispatch commands are included in _collect_all_commands()."""
    page = _make_page()
    token = _render_context.set((page, None))
    try:
        dispatch("event-a")
        dispatch("event-b", detail={"x": 1})
    finally:
        _render_context.reset(token)

    commands = page._collect_all_commands()
    assert len(commands) == 2
    assert commands[0]["cmd"] == "dispatch"
    assert commands[0]["event"] == "event-a"
    assert commands[1]["event"] == "event-b"
    assert commands[1]["detail"] == {"x": 1}

    # After collection, pending dispatches should be cleared
    assert len(page._pending_dispatches) == 0


@pytest.mark.asyncio
async def test_dispatch_commands_in_render_update():
    """Dispatch commands appear in the render_update result."""
    page = _make_page()

    # Queue a dispatch command
    token = _render_context.set((page, None))
    try:
        dispatch("my-event", detail={"id": 99})
    finally:
        _render_context.reset(token)

    # Mock render to return simple HTML
    with patch.object(page, "render", new_callable=AsyncMock) as mock_render:
        mock_render.return_value = Mock(body=b"<html></html>")

        update = await page.render_update(init=False)

        assert update["type"] == "full"
        assert "commands" in update
        dispatch_cmds = [c for c in update["commands"] if c["cmd"] == "dispatch"]
        assert len(dispatch_cmds) == 1
        assert dispatch_cmds[0]["event"] == "my-event"
        assert dispatch_cmds[0]["detail"] == {"id": 99}


@pytest.mark.asyncio
async def test_dispatch_mixed_with_ref_commands():
    """Dispatch commands and ref commands are both collected."""
    page = _make_page()

    # Add a ref with a queued command
    my_ref = ref[InputElement]()
    my_ref._ref_id = "ref-1"
    my_ref._bound_type = "input"
    page._refs_by_id["ref-1"] = my_ref
    my_ref.focus()

    # Queue a dispatch command
    token = _render_context.set((page, None))
    try:
        dispatch("custom-event")
    finally:
        _render_context.reset(token)

    commands = page._collect_all_commands()
    assert len(commands) == 2

    cmd_types = {c["cmd"] for c in commands}
    assert "focus" in cmd_types
    assert "dispatch" in cmd_types


def test_dispatch_from_handler_context():
    """dispatch() works when called from an event handler (via _page_context)."""
    page = _make_page()
    token = _page_context.set(page)
    try:
        dispatch("handler-event", detail={"action": "click"})
    finally:
        _page_context.reset(token)

    assert len(page._pending_dispatches) == 1
    cmd = page._pending_dispatches[0]
    assert cmd["event"] == "handler-event"
    assert cmd["detail"] == {"action": "click"}
