"""Live directive parser."""

import re
from typing import Optional

from pywire_parser.ast_nodes import LiveDirective
from pywire_parser.directives.base import DirectiveParser
from pywire_parser.exceptions import PyWireSyntaxError

#: Same floor as ``@poll.every-<ms>``: every open tab makes a request per tick.
MIN_LIVE_MS = 100


class LiveDirectiveParser(DirectiveParser):
    """Parses ``!live <n>s``, ``!live <n>ms`` or ``!live off``."""

    PATTERN = re.compile(r"^!live\s+(?:(off)|(\d+(?:\.\d+)?)(ms|s))\s*$")

    def can_parse(self, line: str) -> bool:
        stripped = line.strip()
        return stripped == "!live" or stripped.startswith("!live ")

    def parse(self, line: str, line_num: int, col_num: int) -> Optional[LiveDirective]:
        match = self.PATTERN.match(line.strip())
        if not match:
            raise PyWireSyntaxError(
                "!live takes an interval like `!live 2s` or `!live 500ms`, "
                "or `!live off`",
                line=line_num,
                column=col_num,
            )
        off, amount, unit = match.groups()
        if off:
            every_ms = 0
        else:
            every_ms = round(float(amount) * (1000 if unit == "s" else 1))
            if every_ms < MIN_LIVE_MS:
                raise PyWireSyntaxError(
                    f"!live interval must be at least {MIN_LIVE_MS}ms",
                    line=line_num,
                    column=col_num,
                )
        return LiveDirective(
            name="live", line=line_num, column=col_num, every_ms=every_ms
        )
