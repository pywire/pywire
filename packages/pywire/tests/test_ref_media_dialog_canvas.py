import pytest
from unittest.mock import MagicMock, Mock
from pywire.core.refs import (
    ref,
    AnyRef,
    MediaElement,
    DialogElement,
    CanvasElement,
)
from pywire.runtime.page import BasePage


@pytest.fixture
def mock_page():
    page = MagicMock(spec=BasePage)
    page._refs_by_id = {}
    page._parent_page = None
    return page


# --- MediaElement ---


class TestMediaElement:
    def test_create_typed_ref(self):
        """ref[MediaElement]() creates a MediaElement."""
        r = ref[MediaElement]()
        assert isinstance(r, MediaElement)

    def test_play_queues_command(self, mock_page):
        r = ref[MediaElement]()
        r._bind("media", "ref-media-1", mock_page)
        r.play()
        cmds = r._collect_commands()
        assert len(cmds) == 1
        assert cmds[0]["cmd"] == "play"
        assert cmds[0]["refId"] == "ref-media-1"

    def test_pause_queues_command(self, mock_page):
        r = ref[MediaElement]()
        r._bind("media", "ref-media-1", mock_page)
        r.pause()
        cmds = r._collect_commands()
        assert len(cmds) == 1
        assert cmds[0]["cmd"] == "pause"

    def test_load_queues_command(self, mock_page):
        r = ref[MediaElement]()
        r._bind("media", "ref-media-1", mock_page)
        r.load()
        cmds = r._collect_commands()
        assert len(cmds) == 1
        assert cmds[0]["cmd"] == "load"

    def test_initial_state(self):
        r = ref[MediaElement]()
        assert r.current_time == 0.0
        assert r.paused is True
        assert r.duration == 0.0

    def test_update_media_state(self):
        r = ref[MediaElement]()
        r._update_media_state({"currentTime": 42.5, "paused": False, "duration": 120.0})
        assert r.current_time == 42.5
        assert r.paused is False
        assert r.duration == 120.0

    def test_update_media_state_partial(self):
        r = ref[MediaElement]()
        r._update_media_state({"currentTime": 10.0})
        assert r.current_time == 10.0
        assert r.paused is True  # unchanged
        assert r.duration == 0.0  # unchanged

    def test_inherits_html_element(self, mock_page):
        """MediaElement should have HTMLElement methods like focus, blur."""
        r = ref[MediaElement]()
        r._bind("media", "ref-media-1", mock_page)
        r.focus()
        cmds = r._collect_commands()
        assert cmds[0]["cmd"] == "focus"


# --- DialogElement ---


class TestDialogElement:
    def test_create_typed_ref(self):
        r = ref[DialogElement]()
        assert isinstance(r, DialogElement)

    def test_show_modal_queues_command(self, mock_page):
        r = ref[DialogElement]()
        r._bind("dialog", "ref-dialog-1", mock_page)
        r.show_modal()
        cmds = r._collect_commands()
        assert len(cmds) == 1
        assert cmds[0]["cmd"] == "showModal"

    def test_close_queues_command(self, mock_page):
        r = ref[DialogElement]()
        r._bind("dialog", "ref-dialog-1", mock_page)
        r.close("ok")
        cmds = r._collect_commands()
        assert len(cmds) == 1
        assert cmds[0]["cmd"] == "close"
        assert cmds[0]["args"]["returnValue"] == "ok"

    def test_close_default_return_value(self, mock_page):
        r = ref[DialogElement]()
        r._bind("dialog", "ref-dialog-1", mock_page)
        r.close()
        cmds = r._collect_commands()
        assert cmds[0]["args"]["returnValue"] == ""

    def test_open_property(self):
        r = ref[DialogElement]()
        assert r.open is False

    def test_update_dialog_state(self):
        r = ref[DialogElement]()
        r._update_dialog_state({"open": False})
        assert r.open is False


# --- CanvasElement ---


class TestCanvasElement:
    def test_create_typed_ref(self):
        r = ref[CanvasElement]()
        assert isinstance(r, CanvasElement)

    def test_request_data_url_queues_command(self, mock_page):
        r = ref[CanvasElement]()
        r._bind("canvas", "ref-canvas-1", mock_page)
        r.request_data_url()
        cmds = r._collect_commands()
        assert len(cmds) == 1
        assert cmds[0]["cmd"] == "requestDataUrl"
        assert cmds[0]["args"]["type"] == "image/png"

    def test_request_data_url_custom_type(self, mock_page):
        r = ref[CanvasElement]()
        r._bind("canvas", "ref-canvas-1", mock_page)
        r.request_data_url(type="image/jpeg")
        cmds = r._collect_commands()
        assert cmds[0]["args"]["type"] == "image/jpeg"

    def test_data_url_property(self):
        r = ref[CanvasElement]()
        assert r.data_url is None

    def test_update_canvas_state(self):
        r = ref[CanvasElement]()
        r._update_canvas_state({"dataUrl": "data:image/png;base64,abc"})
        assert r.data_url == "data:image/png;base64,abc"


# --- Auto-detection (AnyRef auto-upgrade) ---


class TestAutoDetection:
    def test_anyref_upgrades_to_media_on_bind(self, mock_page):
        """ref() on <video> or <audio> should auto-upgrade to MediaElement."""
        r = ref()
        assert isinstance(r, AnyRef)
        r._bind("media", "ref-video-1", mock_page)
        assert isinstance(r, MediaElement)
        assert not isinstance(r, AnyRef)

    def test_anyref_upgrades_to_dialog_on_bind(self, mock_page):
        r = ref()
        r._bind("dialog", "ref-dialog-1", mock_page)
        assert isinstance(r, DialogElement)

    def test_anyref_upgrades_to_canvas_on_bind(self, mock_page):
        r = ref()
        r._bind("canvas", "ref-canvas-1", mock_page)
        assert isinstance(r, CanvasElement)

    def test_upgraded_media_ref_has_methods(self, mock_page):
        """After auto-upgrade, the ref should have media-specific methods."""
        r = ref()
        r._bind("media", "ref-video-1", mock_page)
        r.play()
        r.pause()
        cmds = r._collect_commands()
        assert len(cmds) == 2
        assert cmds[0]["cmd"] == "play"
        assert cmds[1]["cmd"] == "pause"

    def test_typed_ref_not_upgraded(self, mock_page):
        """ref[MediaElement]() should not be re-upgraded (already correct type)."""
        r = ref[MediaElement]()
        r._bind("media", "ref-video-1", mock_page)
        assert isinstance(r, MediaElement)

    def test_anyref_stays_for_element(self, mock_page):
        """ref() on a generic element stays AnyRef."""
        r = ref()
        r._bind("element", "ref-div-1", mock_page)
        assert isinstance(r, AnyRef)


# --- Command collection includes media commands ---


class TestCommandCollection:
    def test_media_commands_collected(self, mock_page):
        r = ref[MediaElement]()
        r._bind("media", "ref-media-1", mock_page)
        r.play()
        r.focus()
        r.pause()
        cmds = r._collect_commands()
        assert len(cmds) == 3
        assert [c["cmd"] for c in cmds] == ["play", "focus", "pause"]

    def test_dialog_commands_collected(self, mock_page):
        r = ref[DialogElement]()
        r._bind("dialog", "ref-dialog-1", mock_page)
        r.show_modal()
        r.close("done")
        cmds = r._collect_commands()
        assert len(cmds) == 2
        assert [c["cmd"] for c in cmds] == ["showModal", "close"]

    def test_commands_cleared_after_collect(self, mock_page):
        r = ref[MediaElement]()
        r._bind("media", "ref-media-1", mock_page)
        r.play()
        cmds = r._collect_commands()
        assert len(cmds) == 1
        cmds2 = r._collect_commands()
        assert len(cmds2) == 0


# --- Server-side property sync handling ---


class TestRefSyncPropertyHandling:
    @pytest.mark.asyncio
    async def test_media_property_sync(self):
        """Test that _handle_ref_sync handles property syncs for media elements."""
        from pywire.runtime.websocket import WebSocketHandler

        app = Mock()
        handler = WebSocketHandler(app)

        class MockWS:
            scope = {"type": "websocket"}

        ws = MockWS()
        page = BasePage(request=Mock(), params={}, query={}, path={}, url=None)
        media_ref = ref[MediaElement]()
        media_ref._ref_id = "ref-media-1"
        media_ref._bound_type = "media"
        page._refs_by_id["ref-media-1"] = media_ref
        handler.connection_pages[ws] = page

        data = {
            "type": "ref_sync",
            "refId": "ref-media-1",
            "property": "currentTime",
            "value": 42.5,
        }
        await handler._handle_ref_sync(ws, data)
        assert media_ref.current_time == 42.5

    @pytest.mark.asyncio
    async def test_dialog_property_sync(self):
        from pywire.runtime.websocket import WebSocketHandler

        app = Mock()
        handler = WebSocketHandler(app)

        class MockWS:
            scope = {"type": "websocket"}

        ws = MockWS()
        page = BasePage(request=Mock(), params={}, query={}, path={}, url=None)
        dialog_ref = ref[DialogElement]()
        dialog_ref._ref_id = "ref-dialog-1"
        dialog_ref._bound_type = "dialog"
        page._refs_by_id["ref-dialog-1"] = dialog_ref
        handler.connection_pages[ws] = page

        data = {
            "type": "ref_sync",
            "refId": "ref-dialog-1",
            "property": "open",
            "value": False,
        }
        await handler._handle_ref_sync(ws, data)
        assert dialog_ref.open is False

    @pytest.mark.asyncio
    async def test_canvas_property_sync(self):
        from pywire.runtime.websocket import WebSocketHandler

        app = Mock()
        handler = WebSocketHandler(app)

        class MockWS:
            scope = {"type": "websocket"}

        ws = MockWS()
        page = BasePage(request=Mock(), params={}, query={}, path={}, url=None)
        canvas_ref = ref[CanvasElement]()
        canvas_ref._ref_id = "ref-canvas-1"
        canvas_ref._bound_type = "canvas"
        page._refs_by_id["ref-canvas-1"] = canvas_ref
        handler.connection_pages[ws] = page

        data = {
            "type": "ref_sync",
            "refId": "ref-canvas-1",
            "property": "dataUrl",
            "value": "data:image/png;base64,abc123",
        }
        await handler._handle_ref_sync(ws, data)
        assert canvas_ref.data_url == "data:image/png;base64,abc123"
