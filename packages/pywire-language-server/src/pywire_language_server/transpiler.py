import ast
import re
from typing import Dict, List, Optional, Tuple
from .sourcemap import SourceMap


class Transpiler:
    def __init__(self, source: str):
        self.source = source
        self.lines = source.splitlines(keepends=True)
        self.generated_code: List[str] = []
        self.source_map = SourceMap(source, "")
        self.directive_ranges: Dict[str, Tuple[int, int]] = {}
        self.path_routes: Dict[str, str] = {}

        self.current_line_idx = 0
        self.generated_line_idx = 0  # 0-indexed
        self._separator_re = re.compile(r"^\s*(-{3,})\s*html\s*\1\s*$", re.IGNORECASE)

    def transpile(self) -> Tuple[str, SourceMap]:
        """Convert .wire source to virtual .py source with source map."""
        separator_idx = self._find_separator()
        header_end = separator_idx if separator_idx is not None else len(self.lines)

        # Implicit Import
        self.generated_code.append("from pywire import wire\n")
        self.generated_line_idx += 1

        directive_end, python_start, html_start = self._scan_directives(header_end)
        self._emit_framework_stubs()

        # --- Phase 1: Python Section (Definitions) ---
        if separator_idx is not None and python_start is not None:
            python_source_lines = self.lines[python_start:header_end]

            # Process each line for syntax rewriting ($var -> var.value)
            for i, line in enumerate(python_source_lines):
                orig_line_idx = python_start + i
                self._emit_python_line_with_rewrites(line, orig_line_idx)

            # Spacer to separate definitions from expressions
            self.generated_code.append("\n# --- HTML Expressions ---\n")
            self.generated_line_idx += 2

        # --- Phase 2: HTML Section (Expressions) ---
        if separator_idx is not None:
            html_start = separator_idx + 1
        i = html_start
        while i < len(self.lines):
            line = self.lines[i]
            stripped = line.strip()

            if not stripped:
                i += 1
                continue

            if stripped.startswith("!path"):
                start = i
                i = self._handle_path_directive(i)
                self.directive_ranges["path"] = (start, i - 1)
            elif stripped.startswith("!layout"):
                i += 1
            elif stripped.startswith("!"):
                i += 1
            else:
                # HTML line
                i = self._process_html_section(i, len(self.lines))

        full_code = "".join(self.generated_code)
        self.source_map.generated_source = full_code
        return full_code, self.source_map

    def _emit_python_line_with_rewrites(self, line: str, orig_line_idx: int):
        """Emit a python line, replacing $var with var.value and correcting the source map."""
        # Use helper starting at col 0
        stripline = line.rstrip("\r\n")
        text = self._emit_rewritten_segment(
            stripline, orig_line_idx, 0, self.generated_line_idx, 0
        )
        self.generated_code.append(text + "\n")
        self.generated_line_idx += 1

    def _emit_rewritten_segment(
        self,
        text: str,
        orig_line: int,
        orig_col: int,
        gen_line: int,
        start_gen_col: int,
    ) -> str:
        """
        Rewrites $var -> var.value in text, adding mappings.
        Returns the rewritten text string.
        """
        # Split but keep delimiters ($var)
        parts = re.split(r"(\$[a-zA-Z_]\w*)", text)
        current_gen_col = start_gen_col
        current_orig_col = orig_col

        rewritten_parts = []

        for part in parts:
            if not part:
                continue

            if part.startswith("$"):
                # Rewrite: $count -> count.value
                var_name = part[1:]

                # 1. Map 'count' -> 'count'
                # Orig: $count (starts at current_orig_col). 'count' starts at +1.
                # Gen: count (starts at current_gen_col).
                rewritten_parts.append(var_name)
                self.source_map.add_mapping(
                    gen_line=gen_line,
                    gen_col=current_gen_col,
                    orig_line=orig_line,
                    orig_col=current_orig_col + 1,  # Skip $
                    length=len(var_name),
                )
                current_gen_col += len(var_name)

                # 2. Append '.value' (Unmapped)
                # This ensures the length in generated code > original code doesn't confuse the map
                suffix = ".value"
                rewritten_parts.append(suffix)
                current_gen_col += len(suffix)

                # Original consumed length is len("$count")
                current_orig_col += len(part)
            else:
                # Text -> Text
                rewritten_parts.append(part)
                self.source_map.add_mapping(
                    gen_line=gen_line,
                    gen_col=current_gen_col,
                    orig_line=orig_line,
                    orig_col=current_orig_col,
                    length=len(part),
                )
                current_gen_col += len(part)
                current_orig_col += len(part)

        return "".join(rewritten_parts)

    def _find_separator(self) -> Optional[int]:
        for i, line in enumerate(self.lines):
            if self._separator_re.match(line.strip()):
                return i
        return None

    def _scan_directives(self, end_idx: int) -> Tuple[int, Optional[int], int]:
        i = 0
        pending_blank_start: Optional[int] = None

        while i < end_idx:
            stripped = self.lines[i].strip()
            if not stripped:
                if pending_blank_start is None:
                    pending_blank_start = i
                i += 1
                continue

            if stripped.startswith("!path"):
                pending_blank_start = None
                start = i
                i = self._handle_path_directive(i)
                self.directive_ranges["path"] = (start, i - 1)
                continue

            if stripped.startswith("!layout") or stripped.startswith("!"):
                pending_blank_start = None
                i += 1
                continue

            break

        directive_end = i
        if directive_end == end_idx:
            python_start = None
            html_start = (
                pending_blank_start
                if pending_blank_start is not None
                else directive_end
            )
        else:
            python_start = (
                pending_blank_start
                if pending_blank_start is not None
                else directive_end
            )
            html_start = python_start

        return directive_end, python_start, html_start

    def _emit_empty_line(self):
        self.generated_code.append("\n")
        self.generated_line_idx += 1

    def _emit_comment(self, text: str):
        self.generated_code.append(f"# {text.strip()[:50]}...\n")
        self.generated_line_idx += 1

    def _handle_path_directive(self, start_idx: int) -> int:
        line = self.lines[start_idx]

        # Check if it opens a brace
        if "{" in line and "}" not in line:
            # Multi-line directive
            # Consume until we find closing brace
            current_idx = start_idx
            content_accum = []

            while current_idx < len(self.lines):
                line_text = self.lines[current_idx]
                content_accum.append(line_text)
                if "}" in line_text:
                    break
                current_idx += 1

            # Now we have the full block.
            # We want to emit: __path = { ... }
            # Mapping is tricky for multi-line. We map line-by-line.

            full_text = "".join(content_accum)
            match = re.search(r"!path\s*({.*})", full_text, re.DOTALL)
            if match:
                parsed = self._parse_path_routes(match.group(1))
                if parsed is not None:
                    self.path_routes = parsed
                # It's a dict.
                # We emit "__path = <content>"
                # To preserve mapping we should emit each line of the content.
                self.generated_code.append("__path = ")
                # We'll map the FIRST line's `{` part.

                # Simpler strategy: Just dump the lines as is, but prefix the first one?
                # "!path {" -> "__path = {"
                # " 'foo': 'bar'" -> " 'foo': 'bar'"
                # "}" -> "}"

                # First line replacement:
                l0 = content_accum[0]
                l0_fixed = l0.replace("!path", "", 1).lstrip()
                # If l0 was "!path {", l0_fixed is "{".
                # We append "__path = " + l0_fixed
                self.generated_code.append("__path = " + l0_fixed)

                # Map it roughly? For now let's just dump it.
                # Ideally we map "path" to the "!path" keyword location?
                self.generated_line_idx += 1

                for i in range(1, len(content_accum)):
                    self.generated_code.append(content_accum[i])
                    self.generated_line_idx += 1

                return current_idx + 1

            return current_idx + 1
        else:
            # Single line
            parsed = self._parse_path_routes(line.replace("!path", "", 1).strip())
            if parsed is not None:
                self.path_routes = parsed
            self.generated_code.append(
                "__path = " + line.replace("!path", "", 1).strip() + "\n"
            )
            self.generated_line_idx += 1
            return start_idx + 1

    def _parse_path_routes(self, routes_text: str) -> Optional[Dict[str, str]]:
        try:
            expr_ast = ast.parse(routes_text, mode="eval")
        except SyntaxError:
            return None

        if isinstance(expr_ast.body, ast.Dict):
            routes: Dict[str, str] = {}
            for key_node, value_node in zip(expr_ast.body.keys, expr_ast.body.values):
                if not isinstance(key_node, ast.Constant) or not isinstance(
                    key_node.value, str
                ):
                    return None
                if not isinstance(value_node, ast.Constant) or not isinstance(
                    value_node.value, str
                ):
                    return None
                routes[key_node.value] = value_node.value
            return routes

        if isinstance(expr_ast.body, ast.Constant) and isinstance(
            expr_ast.body.value, str
        ):
            return {"main": expr_ast.body.value}

        return None

    def _emit_framework_stubs(self) -> None:
        def _append(text: str) -> None:
            self.generated_code.append(text)
            self.generated_line_idx += text.count("\n")

        route_keys = list(self.path_routes.keys())
        keys_literal = ", ".join([repr(k) for k in route_keys])

        _append("from typing import Literal, overload\n\n")

        # path namespace
        _append("class _PathNamespace:\n")
        for key in route_keys:
            _append(f"    {key}: bool\n")
        if route_keys:
            _append("\n")
            _append(
                f"    @overload\n    def __getitem__(self, key: Literal[{keys_literal}]) -> bool: ...\n"
            )
        _append("    def __getitem__(self, key: str) -> bool: ...\n\n")

        # url namespace
        _append("class _UrlNamespace:\n")
        for key in route_keys:
            _append(f"    {key}: str\n")
        if route_keys:
            _append("\n")
            _append(
                f"    @overload\n    def __getitem__(self, key: Literal[{keys_literal}]) -> str: ...\n"
            )
        _append("    def __getitem__(self, key: str) -> str: ...\n\n")

        # params/query namespaces
        _append("class _ParamsNamespace:\n")
        _append("    def __getitem__(self, key: str) -> str: ...\n")
        _append("    def __getattr__(self, name: str) -> str: ...\n\n")
        _append("class _QueryNamespace:\n")
        _append("    def __getitem__(self, key: str) -> str: ...\n")
        _append("    def __getattr__(self, name: str) -> str: ...\n\n")

        _append("path = _PathNamespace()\n")
        _append("url = _UrlNamespace()\n")
        _append("params = _ParamsNamespace()\n")
        _append("query = _QueryNamespace()\n\n")

    def _process_html_section(self, start_idx: int, safe_limit: int) -> int:
        """Process one or more lines of HTML, extracting interpolations."""

        # We need to scan potentially across lines if a brace is open.
        current_idx = start_idx

        # State
        balance = 0
        in_quote = None
        interpolation_start: Optional[Tuple[int, int]] = None  # (line_idx, char_idx)

        # To handle context wrappers ($if=...), we need to look backwards from the opening brace.
        # But spanning lines makes "looking back" hard if the directive attribute name is on previous line.
        # Example: <div \n $if={...}> is fine.
        # Example: <div $if \n ={...}> -- HTML allows spaces around =.

        # Parsing full HTML carefully is hard.
        # Simplified approach: Tokenize the stream of characters starting from start_idx.

        while current_idx < safe_limit:
            line = self.lines[current_idx]
            i = 0
            while i < len(line):
                char = line[i]

                if in_quote:
                    if char == in_quote:
                        if i > 0 and line[i - 1] != "\\":
                            in_quote = None
                else:
                    if char in ('"', "'"):
                        if balance > 0:
                            # We are inside Python. Quotes matter.
                            in_quote = char
                        else:
                            # We are in HTML. " doesn't stop us from finding {
                            pass

                    elif char == "{":
                        if balance == 0:
                            interpolation_start = (current_idx, i)
                        balance += 1
                    elif char == "}":
                        if balance > 0:
                            balance -= 1
                            if balance == 0:
                                # Found end of interpolation!
                                if interpolation_start is None:
                                    i += 1
                                    continue
                                start_line, start_col = interpolation_start
                                end_line, end_col = current_idx, i

                                self._emit_interpolation(
                                    start_line, start_col, end_line, end_col
                                )
                                interpolation_start = None

                i += 1

            # End of line
            if balance > 0:
                # Continue to next line
                current_idx += 1
            else:
                return current_idx + 1

        return current_idx

    def _emit_interpolation(
        self, start_line: int, start_col: int, end_line: int, end_col: int
    ):
        # Detect Context
        # We look at the text immediately preceding the start brace
        preceding_text = self.lines[start_line][:start_col]
        # We want to find `word=`
        match = re.search(r"([@$][\w\.]+|[\w\-]+)\s*=$", preceding_text.rstrip())

        prefix = ""
        suffix = ""

        if match:
            attr_name = match.group(1)
            if attr_name.startswith("$if") or attr_name.startswith("$show"):
                prefix = "if ("
                suffix = "): pass"
            elif attr_name.startswith("$for"):
                prefix = "for "
                suffix = ": pass"
            elif attr_name.startswith("@"):
                # Event handler
                # @click={foo} -> def __handler(): (foo)
                prefix = "def __handler(): ("
                suffix = ")"

        # Emit prefix
        # We don't append yet, we combine with content
        current_gen_col = len(prefix)

        # Emit Content with Rewrites
        if start_line == end_line:
            # Single line content
            content = self.lines[start_line][start_col + 1 : end_col]
            rewritten_content = self._emit_rewritten_segment(
                content,
                start_line,
                start_col + 1,
                self.generated_line_idx,
                current_gen_col,
            )
            self.generated_code.append(prefix + rewritten_content + suffix + "\n")
            self.generated_line_idx += 1
        else:
            # Multi-line
            # Do best effort: Join lines and rewrite?
            # Or iterate?
            # Iterating is hard because _emit_rewritten_segment assumes one gen_line.
            # If we align lines, we can emit newlines.

            # For multi-line, process per-line to keep line mapping sane.
            l1 = self.lines[start_line][start_col + 1 :].rstrip("\r\n")
            rewritten_l1 = self._emit_rewritten_segment(
                l1, start_line, start_col + 1, self.generated_line_idx, current_gen_col
            )

            # Append prefix + l1 + \n
            # Note: prefix is only added to the first line
            self.generated_code.append(prefix + rewritten_l1 + "\n")
            self.generated_line_idx += 1
            current_gen_col = 0

            # Middle lines
            for l_idx in range(start_line + 1, end_line):
                l_text = self.lines[l_idx].rstrip("\r\n")
                rewritten_text = self._emit_rewritten_segment(
                    l_text, l_idx, 0, self.generated_line_idx, 0
                )
                self.generated_code.append(rewritten_text + "\n")
                self.generated_line_idx += 1

            # Last line
            l_last = self.lines[end_line][:end_col]
            rewritten_last = self._emit_rewritten_segment(
                l_last, end_line, 0, self.generated_line_idx, 0
            )

            # Append last line + suffix + \n
            self.generated_code.append(rewritten_last + suffix + "\n")
            self.generated_line_idx += 1
