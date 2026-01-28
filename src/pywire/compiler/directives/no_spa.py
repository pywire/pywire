"""No-SPA directive parser."""

import re
from typing import Optional

from pywire.compiler.ast_nodes import NoSpaDirective
from pywire.compiler.directives.base import DirectiveParser


class NoSpaDirectiveParser(DirectiveParser):
    """Parses !no_spa directive to disable client-side navigation."""

    PATTERN = re.compile(r"^!no_spa\s*$")

    def can_parse(self, line: str) -> bool:
        """Check if line is !no_spa."""
        return line.strip() == "!no_spa"

    def parse(self, line: str, line_num: int, col_num: int) -> Optional[NoSpaDirective]:
        """Parse !no_spa directive."""
        if not self.PATTERN.match(line.strip()):
            return None

        return NoSpaDirective(name="no_spa", line=line_num, column=col_num)
