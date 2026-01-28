import re
from typing import Optional

from pywire.compiler.ast_nodes import ComponentDirective, Directive
from pywire.compiler.directives.base import DirectiveParser


class ComponentDirectiveParser(DirectiveParser):
    """Parses !component 'path' as Name"""

    def can_parse(self, line: str) -> bool:
        return line.startswith("!component")

    def parse(self, line: str, line_num: int, col_num: int) -> Optional[Directive]:
        # Format: !component 'path/to/file' as ComponentName
        # or !component "path/to/file" as ComponentName

        # Regex to match: !component\s+['"](.+?)['"]\s+as\s+(\w+)
        match = re.search(r"^!component\s+['\"](.+?)['\"]\s+as\s+(\w+)", line)
        if not match:
            # Maybe invalid format
            return None

        path = match.group(1)
        name = match.group(2)

        return ComponentDirective(
            line=line_num, column=col_num, name="!component", path=path, component_name=name
        )
