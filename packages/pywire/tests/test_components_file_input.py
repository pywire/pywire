from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pywire.components import FileInput


@pytest.mark.asyncio
async def test_file_input_validates_and_triggers_select_submit_mode_default() -> None:
    on_select = AsyncMock()
    comp = FileInput(
        None,
        {},
        {},
        name="avatar",
        allowed_names=r"^avatar_.*\.(png|jpg)$",
        min_size=10,
        max_size=100,
        select=on_select,
    )

    event = SimpleNamespace(
        value=[
            {"name": "avatar_ok.png", "size": 42, "type": "image/png"},
        ]
    )
    await comp.change(event)

    assert comp.error == ""
    assert comp.uploading is False
    assert len(comp.files) == 1
    on_select.assert_awaited_once()


@pytest.mark.asyncio
async def test_file_input_validates_and_triggers_select_upload_on_select() -> None:
    on_select = AsyncMock()
    comp = FileInput(
        None,
        {},
        {},
        name="avatar",
        allowed_names=r"^avatar_.*\.(png|jpg)$",
        min_size=10,
        max_size=100,
        select=on_select,
        upload_on="select",
    )

    event = SimpleNamespace(
        value=[
            {"name": "avatar_ok.png", "size": 42, "type": "image/png"},
        ]
    )
    await comp.change(event)

    assert comp.error == ""
    assert comp.uploading is True
    assert len(comp.files) == 1
    on_select.assert_awaited_once()


@pytest.mark.asyncio
async def test_file_input_rejects_bad_filename() -> None:
    comp = FileInput(
        None,
        {},
        {},
        name="avatar",
        allowed_names=r"^avatar_.*\.(png|jpg)$",
    )

    event = SimpleNamespace(
        value=[
            {"name": "bad_name.png", "size": 42, "type": "image/png"},
        ]
    )
    await comp.change(event)

    assert comp.error == "Filename is not allowed"
    assert comp.uploading is False


@pytest.mark.asyncio
async def test_file_input_clear_resets_state() -> None:
    comp = FileInput(None, {}, {}, name="avatar")
    comp._progress_wire.value = 55
    comp._uploading_wire.value = True
    comp._error_wire.value = "boom"
    comp._files_wire.append({"name": "avatar.png", "size": 10, "type": "image/png"})
    comp._upload_ids_wire.append("abc")

    comp.clear()

    assert comp.progress == 0
    assert comp.uploading is False
    assert comp.error == ""
    assert comp.files == []
    assert comp.upload_ids == []


def test_file_input_progress_bridge_clamps_values() -> None:
    comp = FileInput(None, {}, {}, name="avatar")

    comp.progress_input(SimpleNamespace(value="-10"))
    assert comp.progress == 0

    comp.progress_input(SimpleNamespace(value="250"))
    assert comp.progress == 100

    comp.progress_input(SimpleNamespace(value="35"))
    assert comp.progress == 35
