from pywire.runtime.events import (
    create_event_data,
    MouseEventData,
    KeyboardEventData,
    InputEventData,
    FormEventData,
    UIEventData,
    EventData
)

def test_mouse_event():
    raw = {"type": "click", "clientX": 100, "clientY": 200, "altKey": True, "id": "btn1"}
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

if __name__ == "__main__":
    test_mouse_event()
    test_keyboard_event()
    test_input_event()
    test_form_event()
    test_generic_ui_event()
    print("EventData hierarchy tests PASSED!")
