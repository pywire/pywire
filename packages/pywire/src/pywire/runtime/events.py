from typing import Any, Dict, Optional

# The event fields a handler can take by parameter name
# (``def on_input(value)``), each with its key in the event data the client
# sends. The client controls every one of them: they describe what the user
# did. Anything else it sends is only reachable through ``event``, and never
# fills another parameter: inline call arguments (``@click={delete(item.id)}``)
# come from the server alone (see ``handler_args``).
EVENT_PARAMS: Dict[str, str] = {
    "type": "type",
    "id": "id",
    "name": "name",
    "target_id": "id",
    "target_name": "name",
    "target_tag": "tagName",
    "value": "value",
    "values": "values",
    "checked": "checked",
    "input_type": "inputType",
    "form_data": "formData",
    "detail": "detail",
    "key": "key",
    "code": "code",
    "key_code": "keyCode",
    "alt_key": "altKey",
    "ctrl_key": "ctrlKey",
    "meta_key": "metaKey",
    "shift_key": "shiftKey",
    "client_x": "clientX",
    "client_y": "clientY",
    "offset_x": "offsetX",
    "offset_y": "offsetY",
    "page_x": "pageX",
    "page_y": "pageY",
    "screen_x": "screenX",
    "screen_y": "screenY",
    "button": "button",
    "buttons": "buttons",
}


class EventData:
    """Base event — universal fields only."""

    def __init__(self, raw: Dict[str, Any]):
        self.type: str = raw.get("type", "")
        self.target_id: Optional[str] = raw.get("id")
        self.target_name: Optional[str] = raw.get("name")
        self.target_tag: Optional[str] = raw.get("tagName")
        self._raw_data = raw

    def __getattr__(self, name: str) -> Any:
        # Compatibility for extra data or camelCase/snake_case mapping
        # We try snake_case version of whatever the client sends if not found
        try:
            return self._raw_data[name]
        except KeyError:
            # Check for camelCase version of name
            import re

            camel = re.sub(r"(?!^)_([a-z])", lambda x: x.group(1).upper(), name)
            if camel in self._raw_data:
                return self._raw_data[camel]
            return None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        value = getattr(self, key)
        return default if value is None else value


class UIEventData(EventData):
    """Shared modifier keys (mirrors JS UIEvent)."""

    def __init__(self, raw: Dict[str, Any]):
        super().__init__(raw)
        self.alt_key: bool = bool(raw.get("altKey", False))
        self.ctrl_key: bool = bool(raw.get("ctrlKey", False))
        self.meta_key: bool = bool(raw.get("metaKey", False))
        self.shift_key: bool = bool(raw.get("shiftKey", False))


class KeyboardEventData(UIEventData):
    """keydown, keyup, keypress."""

    def __init__(self, raw: Dict[str, Any]):
        super().__init__(raw)
        self.key: str = raw.get("key", "")
        self.code: str = raw.get("code", "")
        self.key_code: int = int(raw.get("keyCode", 0))


class MouseEventData(UIEventData):
    """click, dblclick, mousedown, mousemove, etc."""

    def __init__(self, raw: Dict[str, Any]):
        super().__init__(raw)
        self.client_x: float = float(raw.get("clientX", 0))
        self.client_y: float = float(raw.get("clientY", 0))
        self.offset_x: float = float(raw.get("offsetX", 0))
        self.offset_y: float = float(raw.get("offsetY", 0))
        self.page_x: float = float(raw.get("pageX", 0))
        self.page_y: float = float(raw.get("pageY", 0))
        self.screen_x: float = float(raw.get("screenX", 0))
        self.screen_y: float = float(raw.get("screenY", 0))
        self.button: int = int(raw.get("button", 0))
        self.buttons: int = int(raw.get("buttons", 0))


class InputEventData(EventData):
    """input, change events."""

    def __init__(self, raw: Dict[str, Any]):
        super().__init__(raw)
        self.value: Optional[str] = raw.get("value")
        self.checked: Optional[bool] = raw.get("checked")
        self.input_type: Optional[str] = raw.get("inputType")


class FormEventData(EventData):
    """submit events.

    Also reads like a mapping of the submitted fields, so a plain
    ``@submit`` handler can use ``data["name"]`` or ``data.get("name")``.
    Repeated names (checkbox groups, multiple selects) hold lists.
    """

    def __init__(self, raw: Dict[str, Any]):
        super().__init__(raw)
        self.form_data: Dict[str, Any] = raw.get("formData", {})

    # A submit handler reads its form like a dict: `data["name"]`,
    # `data.get("name")`, `"name" in data`, `dict(data)`. Form fields win
    # over event fields.
    def __getitem__(self, key: str) -> Any:
        if key in self.form_data:
            return self.form_data[key]
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        if key in self.form_data:
            return self.form_data[key]
        return super().get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self.form_data

    def keys(self) -> Any:
        return self.form_data.keys()

    def values(self) -> Any:
        return self.form_data.values()

    def items(self) -> Any:
        return self.form_data.items()

    def __iter__(self) -> Any:
        return iter(self.form_data)

    def __len__(self) -> int:
        return len(self.form_data)

    def __bool__(self) -> bool:
        return True

    @property
    def value(self) -> Any:
        # Convenience: if there's only one item in formData, expose it as .value
        if len(self.form_data) == 1:
            return list(self.form_data.values())[0]
        return self._raw_data.get("value")


def create_event_data(raw: Dict[str, Any]) -> EventData:
    """Factory to create the appropriate subclass based on event type."""
    type_name = raw.get("type", "").lower()

    if type_name in (
        "click",
        "dblclick",
        "mousedown",
        "mouseup",
        "mousemove",
        "mouseenter",
        "mouseleave",
        "mouseover",
        "mouseout",
        "contextmenu",
        "wheel",
    ):
        return MouseEventData(raw)
    if type_name in ("keydown", "keyup", "keypress"):
        return KeyboardEventData(raw)
    if type_name in ("input", "change"):
        return InputEventData(raw)
    if type_name == "submit":
        return FormEventData(raw)
    if any(k in raw for k in ("altKey", "ctrlKey", "metaKey", "shiftKey")):
        return UIEventData(raw)

    return EventData(raw)
