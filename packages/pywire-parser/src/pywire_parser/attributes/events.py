"""Event attribute parser."""

import re
from typing import List, Optional

from pywire_parser.ast_nodes import EventAttribute
from pywire_parser.attributes.base import AttributeParser
from pywire_parser.exceptions import PyWireSyntaxError


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

        # `.optimistic-class-*` tokens must carry a non-empty name after the dash.
        for modifier in modifiers:
            if modifier.startswith("optimistic-class"):
                name = modifier[len("optimistic-class") :]
                if len(name) < 2 or not name.startswith("-"):
                    raise PyWireSyntaxError(
                        f"Optimistic class modifier '{modifier}' in '{attr_name}' "
                        "must be 'optimistic-class-<name>' with a non-empty name.",
                        line=line,
                    )

        # ``@poll`` is a kernel timer primitive, not a DOM event: its only
        # modifier is ``.every-<ms>``, and sub-100ms intervals are a FaaS
        # billing foot-gun.
        if event_type == "poll":
            for modifier in modifiers:
                if not modifier.startswith("every-"):
                    raise PyWireSyntaxError(
                        f"Unknown @poll modifier '{modifier}' in '{attr_name}'. "
                        "@poll only supports '.every-<ms>'.",
                        line=line,
                    )
                raw = modifier[len("every-") :]
                try:
                    ms = int(raw)
                except ValueError:
                    raise PyWireSyntaxError(
                        f"@poll interval '{modifier}' in '{attr_name}' must be "
                        "'.every-<int>' with an integer millisecond value.",
                        line=line,
                    ) from None
                if ms < 100:
                    raise PyWireSyntaxError(
                        f"@poll interval '{modifier}' in '{attr_name}' must be at "
                        "least 100 ms (FaaS billing foot-gun).",
                        line=line,
                    )

        # Strip brackets or quotes
        val = attr_value.strip()
        if val.startswith("{") and val.endswith("}"):
            handler_name = val[1:-1].strip()
        elif (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            handler_name = val[1:-1].strip()
        else:
            raise PyWireSyntaxError(
                f"Event handler for '{attr_name}' must be wrapped in brackets or quotes: "
                f'{attr_name}={{expr}} or {attr_name}="expr"',
                line=line,
            )

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
