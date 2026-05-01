"""No-interactive directive parser."""

import re
from typing import Optional

from pywire_parser.ast_nodes import NoInteractiveDirective
from pywire_parser.directives.base import DirectiveParser


class NoInteractiveDirectiveParser(DirectiveParser):
    """Parses !no_interactive directive — page renders statically.

    The framework still keeps the WebSocket connection alive across SPA
    navigation, but skips event-handler binding and wire wiring for this
    page so client→server interactivity is fully inert here.
    """

    PATTERN = re.compile(r"^!no_interactive\s*$")

    def can_parse(self, line: str) -> bool:
        return line.strip() == "!no_interactive"

    def parse(
        self, line: str, line_num: int, col_num: int
    ) -> Optional[NoInteractiveDirective]:
        if not self.PATTERN.match(line.strip()):
            return None

        return NoInteractiveDirective(
            name="no_interactive", line=line_num, column=col_num
        )
