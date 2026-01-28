"""Event attribute parser."""

import re
from typing import List, Optional

from pywire.compiler.ast_nodes import EventAttribute
from pywire.compiler.attributes.base import AttributeParser
from pywire.compiler.exceptions import PyWireSyntaxError


class EventAttributeParser(AttributeParser):
    """Parses @event attributes (click, submit, etc.)."""

    PREFIX = "@"
    PATTERN = re.compile(r"^@(\w+)$")

    def can_parse(self, attr_name: str) -> bool:
        """Check if attribute starts with @."""
        return attr_name.startswith(self.PREFIX)

    def parse(
        self, attr_name: str, attr_value: str, line: int, col: int
    ) -> Optional[EventAttribute]:
        """Parse @click.prevent.stop={handler_name} attribute."""
        # Remove @ prefix
        full_event = attr_name[1:]
        parts = full_event.split(".")
        event_type = parts[0]
        modifiers = [m for m in parts[1:] if m]

        if not (attr_value.startswith("{") and attr_value.endswith("}")):
            raise PyWireSyntaxError(
                f"Event handler for '{attr_name}' must be wrapped in brackets: "
                f"{attr_name}={{expr}}",
                line=line,
            )

        handler_name = attr_value[1:-1].strip()  # Strip brackets and whitespace

        # Parse handler args if present (future: handler(arg1, arg2))
        handler_args: List[str] = []
        if "(" in handler_name:
            # Future: parse args
            pass

        return EventAttribute(
            name=attr_name,
            value=attr_value,
            event_type=event_type,
            handler_name=handler_name,
            modifiers=modifiers,
            args=handler_args,
            line=line,
            column=col,
        )
