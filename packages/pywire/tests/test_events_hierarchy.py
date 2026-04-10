from pywire.runtime.events import (
    create_event_data,
    MouseEventData,
    KeyboardEventData,
    InputEventData,
    FormEventData,
    UIEventData,
    EventData,
)


def test_mouse_event():
    raw = {
        "type": "click",
        "clientX": 100,
        "clientY": 200,
        "altKey": True,
        "id": "btn1",
    }
    ev = create_event_data(raw)
    assert isinstance(ev, MouseEventData)
    assert ev.type == "click"
    assert ev.client_x == 100
    assert ev.alt_key is True
    assert ev.target_id == "btn1"
    # Test dot access for unknown fields (Alpine-like)
    assert ev.foo is None
    raw["foo"] = "bar"
    assert ev.foo == "bar"


def test_keyboard_event():
    raw = {"type": "keydown", "key": "Enter", "code": "Enter", "shiftKey": True}
    ev = create_event_data(raw)
    assert isinstance(ev, KeyboardEventData)
    assert ev.key == "Enter"
    assert ev.shift_key is True


def test_input_event():
    raw = {"type": "input", "value": "hello", "checked": True, "inputType": "text"}
    ev = create_event_data(raw)
    assert isinstance(ev, InputEventData)
    assert ev.value == "hello"
    assert ev.checked is True
    assert ev.input_type == "text"


def test_form_event():
    raw = {"type": "submit", "formData": {"field1": "val1"}}
    ev = create_event_data(raw)
    assert isinstance(ev, FormEventData)
    assert ev.form_data == {"field1": "val1"}


def test_generic_ui_event():
    raw = {"type": "focus", "altKey": True}
    ev = create_event_data(raw)
    assert isinstance(ev, UIEventData)
    assert ev.alt_key is True


# --- Extended tests ---


def test_dblclick_is_mouse_event():
    raw = {"type": "dblclick", "clientX": 50, "clientY": 75, "button": 0}
    ev = create_event_data(raw)
    assert isinstance(ev, MouseEventData)
    assert ev.client_x == 50
    assert ev.button == 0


def test_contextmenu_is_mouse_event():
    raw = {"type": "contextmenu", "clientX": 200, "clientY": 300, "button": 2}
    ev = create_event_data(raw)
    assert isinstance(ev, MouseEventData)
    assert ev.button == 2


def test_wheel_is_mouse_event():
    raw = {"type": "wheel", "clientX": 10, "clientY": 20, "deltaY": -120}
    ev = create_event_data(raw)
    assert isinstance(ev, MouseEventData)
    # deltaY accessible via __getattr__ fallback
    assert ev.deltaY == -120


def test_focus_is_event_data():
    raw = {"type": "focus", "id": "my-input"}
    ev = create_event_data(raw)
    assert isinstance(ev, EventData)
    assert ev.target_id == "my-input"


def test_blur_is_event_data():
    raw = {"type": "blur", "id": "my-input"}
    ev = create_event_data(raw)
    assert isinstance(ev, EventData)
    assert ev.target_id == "my-input"


def test_focusin_is_event_data():
    raw = {"type": "focusin"}
    ev = create_event_data(raw)
    assert isinstance(ev, EventData)


def test_focusout_is_event_data():
    raw = {"type": "focusout"}
    ev = create_event_data(raw)
    assert isinstance(ev, EventData)


def test_custom_event_is_base_event_data():
    """Custom events should fall through to base EventData."""
    raw = {"type": "item-selected", "detail": {"id": 42, "name": "Widget"}}
    ev = create_event_data(raw)
    assert isinstance(ev, EventData)
    # detail accessible via __getattr__
    assert ev.detail == {"id": 42, "name": "Widget"}


def test_custom_event_without_detail():
    raw = {"type": "ping"}
    ev = create_event_data(raw)
    assert isinstance(ev, EventData)
    assert ev.detail is None


def test_getattr_snake_to_camel():
    """Verify __getattr__ maps snake_case to camelCase for raw data access."""
    raw = {"type": "click", "clientX": 42}
    ev = create_event_data(raw)
    # Access via snake_case should map to camelCase in raw
    assert ev.client_x == 42


def test_getitem_access():
    """Verify dict-style access works."""
    raw = {"type": "click", "clientX": 99}
    ev = create_event_data(raw)
    assert ev["client_x"] == 99


def test_change_event_is_input_data():
    raw = {"type": "change", "value": "new-val", "checked": False}
    ev = create_event_data(raw)
    assert isinstance(ev, InputEventData)
    assert ev.value == "new-val"
    assert ev.checked is False


def test_mouseenter_is_mouse_event():
    raw = {"type": "mouseenter"}
    ev = create_event_data(raw)
    assert isinstance(ev, MouseEventData)


def test_mouseleave_is_mouse_event():
    raw = {"type": "mouseleave"}
    ev = create_event_data(raw)
    assert isinstance(ev, MouseEventData)


def test_unknown_event_with_modifier_keys():
    """Events with modifier keys but unknown type should become UIEventData."""
    raw = {"type": "some-weird-event", "altKey": True, "shiftKey": False}
    ev = create_event_data(raw)
    assert isinstance(ev, UIEventData)
    assert ev.alt_key is True


def test_form_event_value_single_field():
    """FormEventData.value returns the single field's value."""
    raw = {"type": "submit", "formData": {"email": "test@example.com"}}
    ev = create_event_data(raw)
    assert isinstance(ev, FormEventData)
    assert ev.value == "test@example.com"


def test_form_event_value_multiple_fields():
    """FormEventData.value returns raw value when multiple fields exist."""
    raw = {"type": "submit", "formData": {"name": "Alice", "email": "a@b.com"}}
    ev = create_event_data(raw)
    assert isinstance(ev, FormEventData)
    assert ev.value is None


if __name__ == "__main__":
    test_mouse_event()
    test_keyboard_event()
    test_input_event()
    test_form_event()
    test_generic_ui_event()
    test_dblclick_is_mouse_event()
    test_contextmenu_is_mouse_event()
    test_wheel_is_mouse_event()
    test_focus_is_event_data()
    test_blur_is_event_data()
    test_focusin_is_event_data()
    test_focusout_is_event_data()
    test_custom_event_is_base_event_data()
    test_custom_event_without_detail()
    test_getattr_snake_to_camel()
    test_getitem_access()
    test_change_event_is_input_data()
    test_mouseenter_is_mouse_event()
    test_mouseleave_is_mouse_event()
    test_unknown_event_with_modifier_keys()
    test_form_event_value_single_field()
    test_form_event_value_multiple_fields()
    print("All EventData hierarchy tests PASSED!")
