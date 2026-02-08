"""Main PyWire parser orchestrator."""

import ast
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

from lxml import html

from pywire.compiler.ast_nodes import (
    AwaitAttribute,
    CatchAttribute,
    ElifAttribute,
    ElseAttribute,
    EventAttribute,
    ExceptAttribute,
    FieldValidationRules,
    FinallyAttribute,
    ForAttribute,
    FormValidationSchema,
    IfAttribute,
    InterpolationNode,
    ModelAttribute,
    ParsedPyWire,
    ReactiveAttribute,
    SpecialAttribute,
    SpreadAttribute,
    TemplateNode,
    ThenAttribute,
    TryAttribute,
)
from pywire.compiler.attributes.base import AttributeParser
from pywire.compiler.attributes.conditional import ConditionalAttributeParser
from pywire.compiler.attributes.events import EventAttributeParser
from pywire.compiler.attributes.form import ModelAttributeParser
from pywire.compiler.attributes.loop import KeyAttributeParser, LoopAttributeParser
from pywire.compiler.directives.base import DirectiveParser
from pywire.compiler.directives.component import ComponentDirectiveParser
from pywire.compiler.directives.context import ContextDirectiveParser
from pywire.compiler.directives.layout import LayoutDirectiveParser
from pywire.compiler.directives.no_spa import NoSpaDirectiveParser
from pywire.compiler.directives.path import PathDirectiveParser
from pywire.compiler.directives.props import PropsDirectiveParser
from pywire.compiler.exceptions import PyWireSyntaxError
from pywire.compiler.interpolation.jinja import JinjaInterpolationParser


class PyWireParser:
    """Main parser orchestrator."""

    _separator_re = re.compile(r"^\s*(-{3,})\s*html\s*\1\s*$", re.IGNORECASE)

    def __init__(self) -> None:
        # Directive registry
        self.directive_parsers: List[DirectiveParser] = [
            PathDirectiveParser(),
            NoSpaDirectiveParser(),
            LayoutDirectiveParser(),
            ComponentDirectiveParser(),
            PropsDirectiveParser(),
            ContextDirectiveParser(),
        ]

        # Attribute parser chain
        self.attribute_parsers: List[AttributeParser] = [
            EventAttributeParser(),
            ConditionalAttributeParser(),
            LoopAttributeParser(),
            KeyAttributeParser(),
            ModelAttributeParser(),
        ]

        # Interpolation parser (pluggable)
        self.interpolation_parser = JinjaInterpolationParser()

    def parse_file(self, file_path: Path) -> ParsedPyWire:
        """Parse a .pywire file."""
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        return self.parse(content, str(file_path))

    def parse(self, content: str, file_path: str = "") -> ParsedPyWire:
        """Parse PyWire content."""
        self.file_path = file_path
        lines = content.split("\n")
        separator_index = self._find_separator_line(lines, file_path)

        python_section = ""
        python_start_line = -1
        template_lines: List[str] = []

        if separator_index is not None:
            header_lines = lines[:separator_index]

            # Parse directives at the top of the header, remaining lines are Python
            directives, python_lines, python_start_line = self._parse_header_sections(
                header_lines
            )
            python_section = "\n".join(python_lines)

            # HTML comes after the separator; pad to preserve line numbers
            template_lines = [""] * (separator_index + 1) + lines[separator_index + 1 :]
        else:
            # No separator - validate that there's no malformed separator or orphaned Python code
            self._validate_no_orphaned_python(lines, file_path)
            directives, template_lines = self._parse_directives_and_template(lines)

        # Parse directives/template sections already handled above

        # Parse template HTML using lxml
        template_html = "\n".join(template_lines)
        template_nodes = []

        if template_html.strip():
            # Pre-process: Replace <head> with <pywire-head> to preserve it
            # lxml strips standalone <head> tags in fragment mode
            import re

            template_html = re.sub(
                r"<head(\s|>|/>)", r"<pywire-head\1", template_html, flags=re.IGNORECASE
            )
            template_html = re.sub(
                r"</head>", r"</pywire-head>", template_html, flags=re.IGNORECASE
            )

            # Pre-process: Handle unquoted attribute values with braces (Svelte/React style)
            # Regex: attr={value} -> attr="{value}"
            # This allows lxml to parse attributes containing spaces (e.g. @click={count += 1})
            # Limitation: Does not handle nested braces for now.
            def quote_wrapper(match: re.Match[str]) -> str:
                attr = match.group(1)
                value = match.group(2)
                # If value contains double quotes, wrap in single quotes
                if '"' in value:
                    return f"{attr}='{{{value}}}'"
                return f'{attr}="{{{value}}}"'

            template_html = re.sub(
                r"([a-zA-Z0-9_:@$-]+)=\{([^{}]*)\}", quote_wrapper, template_html
            )

            # Pre-process: Handle {**spread} syntax
            # Convert {**...} to __pywire_spread__="{**...}" so lxml can parse it
            # Regex: look for {** followed by anything until } preceded by
            # whitespace or start of string
            # Be careful not to match inside string literals or text content if avoidable.
            # Simple heuristic: Only match if it looks like an attribute (preceded by space)
            # and strictly follows {** pattern.
            template_html = re.sub(
                r'(?<=[\s"\'])(\{\*\*.*?\})', r'__pywire_spread__="\1"', template_html
            )

            # Shorthand for <template> is <$ ... /> or similar? No, only {$tag} now.
            # We don't support <$if> etc anymore.

            # NEW: Handle brace-based control flow {$tag ...} -> <pywire-tag expr="...">
            # NEW: Handle brace-based control flow {$tag ...} -> <pywire-tag expr="...">
            def brace_tag_replacer(match: re.Match) -> str:
                tag = match.group(1).lower()
                expr = match.group(2) or ""

                # Only process known control flow tags for brace syntax
                # (Note: $show is a special attribute/tag but not a block in brace syntax)
                brace_control_flow_tags = {
                    "if",
                    "else",
                    "elif",
                    "for",
                    "await",
                    "then",
                    "catch",
                    "try",
                    "except",
                    "finally",
                    "html",
                }

                if tag not in brace_control_flow_tags:
                    # Return original match if not a control flow tag (e.g. {$count})
                    return match.group(0)

                # Tags that are markers/branches and don't have closing tags in brace syntax
                self_closing_tags = {
                    "else",
                    "elif",
                    "except",
                    "finally",
                    "then",
                    "catch",
                    "html",
                }
                suffix = " />" if tag in self_closing_tags else ">"

                if expr:
                    # Simple escape for quotes to allow lxml to parse the attribute
                    safe_expr = expr.replace('"', "&quot;")
                    return f'<pywire-{tag} expr="{safe_expr}"{suffix}'
                return f"<pywire-{tag}{suffix}"

            template_html = re.sub(
                r"\{\$([a-zA-Z0-9_-]+)(?:\s+(.*?))?\}",
                brace_tag_replacer,
                template_html,
            )
            template_html = re.sub(
                r"\{/([a-zA-Z0-9_-]+)\}", r"</pywire-\1>", template_html
            )

            # Preprocess shorthand bindings: {attr} -> __pw_sh_attr=""
            # We must limit this to inside tags to avoid replacing content.
            # Heuristic: Match <tag ...> blocks and replace inside them.
            def tag_shorthand_wrapper(match: re.Match[str]) -> str:
                tag_content = match.group(0)

                # Replace {identifier} with __pw_sh_identifier=""
                # Lookbehind for whitespace, Lookahead for whitespace/>/end
                # Regex: (?<=\s)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?=\s|/|>)
                processed_tag = re.sub(
                    r"(?<=\s)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?=\s|/|>)",
                    r'__pw_sh_\1=""',
                    tag_content,
                )

                # Replace @attr= with __pw_on_attr= (lxml compatibility for Windows)
                processed_tag = re.sub(
                    r"@([a-zA-Z0-9_-]+)=", r"__pw_on_\1=", processed_tag
                )
                # Replace $attr= with __pw_dir_attr= (lxml compatibility for Windows)
                processed_tag = re.sub(
                    r"\$([a-zA-Z0-9_-]+)=", r"__pw_dir_\1=", processed_tag
                )

                # NEW: Handle boolean shorthands: $permanent -> data-pywire-permanent="true"
                processed_tag = re.sub(
                    r"(?<=\s)\$permanent(?=\s|/|>)",
                    r'data-pywire-permanent="true"',
                    processed_tag,
                )
                # NEW: Handle boolean shorthands: $reload -> data-pywire-reload="true"
                processed_tag = re.sub(
                    r"(?<=\s)\$reload(?=\s|/|>)",
                    r'data-pywire-reload="true"',
                    processed_tag,
                )

                return processed_tag

            # Apply to all tags
            template_html = re.sub(
                r"(<[a-zA-Z0-9_-].*?>)",
                tag_shorthand_wrapper,
                template_html,
                flags=re.DOTALL,
            )

            # lxml.html.fragments_fromstring handles multiple top-level elements
            # It returns a list of elements and strings (for top-level text)
            try:
                # fragments_fromstring might raise error if html is empty or very partial
                # Check for full document to preserve head/body
                clean_html = template_html.strip().lower()
                if clean_html.startswith("<!doctype") or clean_html.startswith("<html"):
                    root = html.fromstring(template_html)
                    fragments = [root]
                else:
                    fragments = html.fragments_fromstring(template_html)

                for frag in fragments:
                    if isinstance(frag, str):
                        # Top-level text
                        # Approximation: assume it starts at line 1 if first, or...
                        # lxml doesn't give line specific info for string fragments.
                        # We'll use 0 or try to track line count (hard without full context).
                        text_nodes = self._parse_text(frag, start_line=0)
                        if text_nodes:
                            template_nodes.extend(text_nodes)
                    else:
                        # Element
                        mapped_node = self._map_node(frag)
                        template_nodes.append(mapped_node)

                        # Handle tail text of top-level element (text after it)
                        # Wait, lxml fragments_fromstring returns mixed list of elements and strings
                        # so tail text is usually returned as a subsequent string fragment.
                        # BUT, documentation says: "Returns a list of the elements found..."
                        # It doesn't always guarantee correct tail handling for top level.
                        # Let's verify:
                        # fragments_fromstring("<div></div>text") -> [Element div, "text"]
                        # elements tail is probably not set if it's top level list??
                        # Actually if we use fragments_fromstring, checking tail is safe.

                        if frag.tail:
                            # Wait, if fragments_fromstring returns it as separate string
                            # item, we duplicate?
                            # Let's rely on testing. If lxml puts it in list,
                            # frag.tail should be None?
                            # Nope, lxml behavior:
                            # fragments_fromstring("<a></a>tail") -> [Element a]
                            # The tail is attached to 'a'.
                            # So we DO need to handle tail here.

                            # Tail starts after element processing.
                            # Simple approximation: uses element.sourceline.
                            # For better accuracy we'd count lines in element+children.
                            tail_nodes = self._parse_text(
                                frag.tail, start_line=getattr(frag, "sourceline", 0)
                            )
                            if tail_nodes:
                                template_nodes.extend(tail_nodes)

            except PyWireSyntaxError:
                raise
            except Exception:
                # Failed to parse, maybe empty or purely comment?
                # or critical error
                import traceback

                traceback.print_exc()
                pass

        # Parse Python code
        python_ast = None
        if python_section.strip():
            try:
                # Don't silence SyntaxError - let it bubble up so user knows their code is invalid
                from pywire.compiler.preprocessor import preprocess_python_code

                preprocessed_code = preprocess_python_code(python_section)
                python_ast = ast.parse(preprocessed_code)
            except SyntaxError as e:
                # Calculate correct line number
                # python_start_line is 0-indexed line number of first python line
                # e.lineno is 1-indexed relative to python_section
                actual_line = python_start_line + (e.lineno or 1)

                raise PyWireSyntaxError(
                    f"Python syntax error: {e.msg}",
                    file_path=file_path,
                    line=actual_line,
                )

        if python_ast and python_start_line >= 0:
            # Shift line numbers to match original file
            # python_start_line is index of first python line
            # Current AST lines start at 1.
            # We want line 1 to map to python_start_line + 1
            ast.increment_lineno(python_ast, python_start_line)

        return ParsedPyWire(
            directives=directives,
            template=template_nodes,
            python_code=python_section,
            python_ast=python_ast,
            file_path=file_path,
        )

    def _find_separator_line(
        self, lines: List[str], file_path: str
    ) -> Union[int, None]:
        separator_indices = []

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue

            if self._separator_re.match(stripped):
                separator_indices.append(i)
                continue

            if self._looks_like_separator_line(stripped):
                raise PyWireSyntaxError(
                    f"Malformed separator on line {i + 1}: '{stripped}'. "
                    "Expected symmetric dashes around 'html', e.g. '---html---'.",
                    file_path=file_path,
                    line=i + 1,
                )

        if len(separator_indices) > 1:
            raise PyWireSyntaxError(
                "Multiple HTML separators found. Only one '---html---' line is allowed.",
                file_path=file_path,
                line=separator_indices[1] + 1,
            )

        return separator_indices[0] if separator_indices else None

    def _looks_like_separator_line(self, stripped: str) -> bool:
        if not stripped:
            return False
        if "html" in stripped.lower() and "-" in stripped:
            return True
        if all(c == "-" for c in stripped) and len(stripped) >= 3:
            return True
        return False

    def _parse_header_sections(
        self, header_lines: List[str]
    ) -> Tuple[List[Any], List[str], int]:
        directives: List[Any] = []
        python_lines: List[str] = []
        pending_blanks: List[str] = []
        python_start_line = -1

        i = 0
        while i < len(header_lines):
            line = header_lines[i]
            line_stripped = line.strip()
            line_num = i + 1

            if not line_stripped:
                pending_blanks.append(line)
                i += 1
                continue

            found_directive = False
            for parser in self.directive_parsers:
                if parser.can_parse(line_stripped):
                    directive = parser.parse(line_stripped, line_num, 0)
                    if directive:
                        directives.append(directive)
                        found_directive = True
                        pending_blanks = []
                        i += 1
                        break

                    accumulated = line_stripped
                    brace_count = accumulated.count("{") - accumulated.count("}")
                    bracket_count = accumulated.count("[") - accumulated.count("]")
                    paren_count = accumulated.count("(") - accumulated.count(")")

                    j = i + 1
                    while (
                        brace_count > 0 or bracket_count > 0 or paren_count > 0
                    ) and j < len(header_lines):
                        next_line = header_lines[j].strip()
                        accumulated += "\n" + next_line
                        brace_count += next_line.count("{") - next_line.count("}")
                        bracket_count += next_line.count("[") - next_line.count("]")
                        paren_count += next_line.count("(") - next_line.count(")")
                        j += 1

                    directive = parser.parse(accumulated, line_num, 0)
                    if directive:
                        directives.append(directive)
                        found_directive = True
                        pending_blanks = []
                        i = j
                        break
                    break

            if found_directive:
                continue

            python_start_line = i - len(pending_blanks)
            python_lines.extend(pending_blanks)
            python_lines.extend(header_lines[i:])
            pending_blanks = []
            break

        return directives, python_lines, python_start_line

    def _parse_directives_and_template(
        self, all_lines: List[str]
    ) -> Tuple[List[Any], List[str]]:
        directives: List[Any] = []
        template_lines: List[str] = []
        directives_done = False

        i = 0
        while i < len(all_lines):
            old_i = i
            line = all_lines[i]
            line_stripped = line.strip()
            line_num = i + 1

            if not line_stripped:
                if directives_done:
                    template_lines.append(line)
                i += 1
                continue

            found_directive = False
            if not directives_done:
                for parser in self.directive_parsers:
                    if parser.can_parse(line_stripped):
                        directive = parser.parse(line_stripped, line_num, 0)
                        if directive:
                            directives.append(directive)
                            found_directive = True
                            i += 1
                            break

                        accumulated = line_stripped
                        brace_count = accumulated.count("{") - accumulated.count("}")
                        bracket_count = accumulated.count("[") - accumulated.count("]")
                        paren_count = accumulated.count("(") - accumulated.count(")")

                        j = i + 1

                        while (
                            brace_count > 0 or bracket_count > 0 or paren_count > 0
                        ) and j < len(all_lines):
                            next_line = all_lines[j].strip()
                            accumulated += "\n" + next_line
                            brace_count += next_line.count("{") - next_line.count("}")
                            bracket_count += next_line.count("[") - next_line.count("]")
                            paren_count += next_line.count("(") - next_line.count(")")
                            j += 1

                        directive = parser.parse(accumulated, line_num, 0)
                        if directive:
                            directives.append(directive)
                            found_directive = True
                            i = j
                            break
                        i += 1
                        break

            if found_directive:
                for _ in range(i - old_i):
                    template_lines.append("")
            else:
                directives_done = True
                template_lines.append(line)
                i += 1

        return directives, template_lines

    def _parse_text(
        self, text: str, start_line: int = 0, raw_text: bool = False
    ) -> List[TemplateNode]:
        """Helper to parse text string into list of text/interpolation nodes."""
        if not text:
            return []

        if raw_text:
            # Bypass interpolation for raw text elements (script, style)
            return [
                TemplateNode(
                    tag=None, text_content=text, line=start_line, column=0, is_raw=True
                )
            ]

        parts = self.interpolation_parser.parse(text, line=start_line, col=0)
        nodes = []
        for part in parts:
            if isinstance(part, str):
                if parts:  # Keep whitespace unless explicitly stripping policy?
                    # Current policy seems to be keep unless empty?
                    # "if not text.strip(): return" was in old parser
                    # But if we are inside <pre>, we need it.
                    # BS4/lxml default to preserving.
                    nodes.append(
                        TemplateNode(
                            tag=None, text_content=part, line=start_line, column=0
                        )
                    )
            else:
                node = TemplateNode(
                    tag=None, text_content=None, line=part.line, column=part.column
                )
                node.special_attributes = [part]
                nodes.append(node)
        return nodes

    def _map_node(self, element: html.HtmlElement) -> TemplateNode:
        # lxml elements have tag, attrib, text, tail

        # Parse attributes
        regular_attrs, special_attrs = self._parse_attributes(dict(element.attrib))

        node = TemplateNode(
            tag=element.tag,
            attributes=regular_attrs,
            special_attributes=special_attrs,
            line=getattr(element, "sourceline", 0),
            column=0,
        )

        # Handle inner text (before first child)
        if element.text:
            is_raw = isinstance(element.tag, str) and element.tag.lower() in (
                "script",
                "style",
            )
            text_nodes = self._parse_text(
                element.text,
                start_line=getattr(element, "sourceline", 0),
                raw_text=is_raw,
            )
            if text_nodes:
                node.children.extend(text_nodes)

        # Handle Control Flow Blocks (pywire-if, pywire-show, pywire-for, etc.)
        # These are preprocessed from <$tag> or {$tag}
        tag_str = element.tag if isinstance(element.tag, str) else ""
        tag_lower = tag_str.lower()

        control_flow_tags = (
            "pywire-if",
            "pywire-for",
            "pywire-elif",
            "pywire-else",
            "pywire-try",
            "pywire-except",
            "pywire-finally",
            "pywire-await",
            "pywire-then",
            "pywire-catch",
            "pywire-html",
        )
        if tag_lower in control_flow_tags:
            node.tag = None  # Act as <template> wrapper

            # Extract condition/expression from attributes
            # Priority:
            # 1. Explicit special attribute ($if, $show, $for)
            # 2. First reactive attribute (value is expression)
            # 3. First regular attribute (value is string -> treated as expression?)

            if tag_lower == "pywire-if":
                # Check for existing IfAttribute
                if not any(isinstance(a, IfAttribute) for a in node.special_attributes):
                    # Check for 'expr' attribute from brace syntax
                    expr_val = node.attributes.pop("expr", None)
                    if expr_val:
                        node.special_attributes.append(
                            IfAttribute(
                                name="$if",
                                value="",
                                condition=expr_val,
                                line=0,
                                column=0,
                            )
                        )
                    else:
                        # Find first reactive attribute to use as condition
                        found = False
                        for attr in node.special_attributes:
                            if isinstance(attr, ReactiveAttribute):
                                node.special_attributes.append(
                                    IfAttribute(
                                        name="$if",
                                        value="",
                                        condition=attr.expr,
                                        line=0,
                                        column=0,
                                    )
                                )
                                node.special_attributes.remove(attr)
                                found = True
                                break

                        if not found:
                            # Check regular attributes (e.g. condition="exp")
                            # Convert first regular attribute to IfAttribute
                            if node.attributes:
                                key, val = list(node.attributes.items())[0]
                                node.special_attributes.append(
                                    IfAttribute(
                                        name="$if",
                                        value="",
                                        condition=val,
                                        line=0,
                                        column=0,
                                    )
                                )
                                del node.attributes[key]

            elif tag_lower == "pywire-for":
                # Must have ForAttribute
                found_for = False
                for attr in node.special_attributes:
                    if isinstance(attr, ForAttribute):
                        found_for = True
                        break

                if not found_for:
                    # Check for 'expr' attribute from brace syntax
                    expr_val = node.attributes.pop("expr", None)
                    if expr_val:
                        # Parse "item in items, key=item.id" or "idx, item in enumerate(items), key=idx"
                        key_expr = None
                        loop_expr = expr_val

                        # Look for ", key=" to separate key expression
                        if ", key=" in expr_val:
                            loop_expr, key_part = expr_val.rsplit(", key=", 1)
                            key_expr = key_part.strip()
                        elif expr_val.count(",") == 1:
                            # Legacy support for "item in items, some_key" (if it was ever supported)
                            # or just handling a single comma that might be a key separator if it's not a tuple
                            parts = expr_val.split(",", 1)
                            if " in " in parts[0]:
                                loop_expr = parts[0].strip()
                                key_part = parts[1].strip()
                                if key_part.startswith("key="):
                                    key_expr = key_part[4:].strip()
                                else:
                                    # Not a key separator, maybe a trailing comma or something else
                                    loop_expr = expr_val.strip().rstrip(",")

                        # Parse loop_expr into vars and iterable
                        loop_parts = loop_expr.split(" in ", 1)
                        if len(loop_parts) == 2:
                            loop_vars = loop_parts[0].strip()
                            iterable = loop_parts[1].strip()
                            node.special_attributes.append(
                                ForAttribute(
                                    name="$for",
                                    value="",
                                    is_template_tag=False,
                                    loop_vars=loop_vars,
                                    iterable=iterable,
                                    key=key_expr,
                                    line=0,
                                    column=0,
                                )
                            )

            elif tag_lower == "pywire-else":
                node.special_attributes.append(
                    ElseAttribute(name="$else", value="", line=0, column=0)
                )
            elif tag_lower == "pywire-elif":
                expr_val = node.attributes.pop("expr", "")
                node.special_attributes.append(
                    ElifAttribute(
                        name="$elif", value="", condition=expr_val, line=0, column=0
                    )
                )
            elif tag_lower == "pywire-try":
                node.special_attributes.append(
                    TryAttribute(name="$try", value="", line=0, column=0)
                )
            elif tag_lower == "pywire-except":
                expr_val = node.attributes.pop("expr", "")
                # Parse "Exception as e"
                exc_type = expr_val
                alias = None
                if " as " in expr_val:
                    exc_type, alias = expr_val.split(" as ", 1)
                node.special_attributes.append(
                    ExceptAttribute(
                        name="$except",
                        value="",
                        exception_type=exc_type.strip(),
                        alias=alias.strip() if alias else None,
                        line=0,
                        column=0,
                    )
                )
            elif tag_lower == "pywire-finally":
                node.special_attributes.append(
                    FinallyAttribute(name="$finally", value="", line=0, column=0)
                )
            elif tag_lower == "pywire-await":
                expr_val = node.attributes.pop("expr", "")
                node.special_attributes.append(
                    AwaitAttribute(
                        name="$await", value="", expression=expr_val, line=0, column=0
                    )
                )
            elif tag_lower == "pywire-then":
                expr_val = node.attributes.pop("expr", "")
                node.special_attributes.append(
                    ThenAttribute(
                        name="$then",
                        value="",
                        variable=expr_val.strip() if expr_val else None,
                        line=0,
                        column=0,
                    )
                )
            elif tag_lower == "pywire-catch":
                expr_val = node.attributes.pop("expr", "")
                node.special_attributes.append(
                    CatchAttribute(
                        name="$catch",
                        value="",
                        variable=expr_val.strip() if expr_val else None,
                        line=0,
                        column=0,
                    )
                )
            elif tag_lower == "pywire-html":
                expr_val = node.attributes.pop("expr", "")
                node.tag = None
                node.special_attributes.append(
                    InterpolationNode(
                        expression=expr_val,
                        is_raw=True,
                        line=node.line,
                        column=node.column,
                    )
                )

        # Handle children
        for child in element:
            # Special logic: lxml comments are Elements with generic function tag
            if isinstance(child, html.HtmlComment):
                continue  # Skip comments
            if not isinstance(child.tag, str):
                # Processing instruction etc
                continue

            # 1. Map child element
            child_node = self._map_node(child)

            # Enforce single root check for pywire-for (mapped to tag=None with ForAttribute)
            # If child_node is a control flow block (tag=None) and has ForAttribute,
            # we need to ensure it has exactly one child element (TemplateNode with tag!=None).
            # But here we are appending child_node to current node.
            # The structure of child_node for <pywire-for> will be:
            # TemplateNode(tag=None, attributes=[], special_attributes=[ForAttribute], children=[...])
            # We should validate children count inside _map_node for pywire-for.

            # Enforce single root check for pywire-for if no $else is present
            # We check if the current child being added is a second element for a for-loop
            for_attr = next(
                (a for a in node.special_attributes if isinstance(a, ForAttribute)),
                None,
            )
            if for_attr and not node.tag:
                # Keyed loops can have multiple roots (diffing supported)
                if not for_attr.key:
                    # Count non-text elements already in node.children
                    real_children = [c for c in node.children if c.tag is not None]
                    if real_children and child_node.tag is not None:
                        # Check if any child (including the new one) has ElseAttribute
                        has_else = any(
                            isinstance(a, ElseAttribute)
                            for c in node.children
                            for a in c.special_attributes
                        )
                        has_else = has_else or any(
                            isinstance(a, ElseAttribute)
                            for a in child_node.special_attributes
                        )

                        if not has_else:
                            raise PyWireSyntaxError(
                                "Control flow block <$for> must have exactly one root element (unless using {$else} or key=...).",
                                file_path=self.file_path,
                                line=child_node.line,
                            )

            node.children.append(child_node)

            # 2. Handle child's tail (text immediately after child, before next sibling)
            if child.tail:
                tail_nodes = self._parse_text(
                    child.tail, start_line=getattr(child, "sourceline", 0)
                )
                if tail_nodes:
                    node.children.extend(tail_nodes)

        # === Form Validation Schema Extraction ===
        # If this is a <form> with @submit, extract validation rules from child inputs
        if isinstance(element.tag, str) and element.tag.lower() == "form":
            submit_attr = None
            model_attr = None
            for attr in node.special_attributes:
                if isinstance(attr, EventAttribute) and attr.event_type == "submit":
                    submit_attr = attr
                elif isinstance(attr, ModelAttribute):
                    model_attr = attr

            if submit_attr:
                # Build validation schema from form inputs
                schema = self._extract_form_validation_schema(node)
                if model_attr:
                    schema.model_name = model_attr.model_name
                submit_attr.validation_schema = schema

        return node

    def _extract_form_validation_schema(
        self, form_node: TemplateNode
    ) -> FormValidationSchema:
        """Extract validation rules from form inputs."""
        schema = FormValidationSchema()

        def visit_node(node: TemplateNode) -> None:
            if not node.tag:
                return

            tag_lower = node.tag.lower()

            # Check for input, textarea, select with name attribute
            if tag_lower in ("input", "textarea", "select"):
                name = node.attributes.get("name")
                if name:
                    rules = self._extract_field_rules(node, name)
                    schema.fields[name] = rules

            # Recurse into children
            for child in node.children:
                visit_node(child)

        for child in form_node.children:
            visit_node(child)

        return schema

    def _extract_field_rules(
        self, node: TemplateNode, field_name: str
    ) -> FieldValidationRules:
        """Extract validation rules from a single input node."""
        attrs = node.attributes
        special_attrs = node.special_attributes

        rules = FieldValidationRules(name=field_name)

        # Required - static or reactive
        if "required" in attrs:
            rules.required = True

        # Pattern
        if "pattern" in attrs:
            rules.pattern = attrs["pattern"]

        # Length constraints
        if "minlength" in attrs:
            try:
                rules.minlength = int(attrs["minlength"])
            except ValueError:
                pass
        if "maxlength" in attrs:
            try:
                rules.maxlength = int(attrs["maxlength"])
            except ValueError:
                pass

        # Min/max (for number, date, etc.)
        if "min" in attrs:
            rules.min_value = attrs["min"]
        if "max" in attrs:
            rules.max_value = attrs["max"]

        # Step
        if "step" in attrs:
            rules.step = attrs["step"]

        # Input type
        if "type" in attrs:
            rules.input_type = attrs["type"].lower()
        elif node.tag and node.tag.lower() == "textarea":
            rules.input_type = "textarea"
        elif node.tag and node.tag.lower() == "select":
            rules.input_type = "select"

        # Title (custom error message)
        if "title" in attrs:
            rules.title = attrs["title"]

        # File validation
        if "accept" in attrs:
            # Split by comma
            rules.allowed_types = [t.strip() for t in attrs["accept"].split(",")]

        if "max-size" in attrs:
            val = attrs["max-size"].lower().strip()
            multiplier = 1
            if val.endswith("kb") or val.endswith("k"):
                multiplier = 1024
                val = val.rstrip("kb")
            elif val.endswith("mb") or val.endswith("m"):
                multiplier = 1024 * 1024
                val = val.rstrip("mb")
            elif val.endswith("gb") or val.endswith("g"):
                multiplier = 1024 * 1024 * 1024
                val = val.rstrip("gb")

            try:
                rules.max_size = int(float(val) * multiplier)
            except ValueError:
                pass

        # Check for reactive validation attributes (:required, :min, :max)
        from pywire.compiler.ast_nodes import ReactiveAttribute

        for attr in special_attrs:
            if isinstance(attr, ReactiveAttribute):
                if attr.name == "required":
                    rules.required_expr = attr.expr
                elif attr.name == "min":
                    rules.min_expr = attr.expr
                elif attr.name == "max":
                    rules.max_expr = attr.expr

        return rules

    def _parse_attributes(
        self, attrs: Dict[str, Any]
    ) -> Tuple[dict, List[Union[SpecialAttribute, InterpolationNode]]]:
        """Separate regular attrs from special ones."""
        regular = {}
        special: List[Union[SpecialAttribute, InterpolationNode]] = []

        for name, value in attrs.items():
            # Unescape special characters encoded for lxml compatibility
            if name.startswith("__pw_on_"):
                name = "@" + name[len("__pw_on_") :]
            elif name.startswith("__pw_dir_"):
                name = "$" + name[len("__pw_dir_") :]
            elif name.startswith("__pw_sh_"):
                # Shorthand binding: __pw_sh_attr -> {attr}
                attr_name = name[len("__pw_sh_") :]
                special.append(
                    ReactiveAttribute(
                        name=attr_name,
                        value=f"{{{attr_name}}}",
                        expr=attr_name,
                        line=0,
                        column=0,
                    )
                )
                continue

            if value is None:
                value = ""

            parsed = False
            for parser in self.attribute_parsers:
                if parser.can_parse(name):
                    attr = parser.parse(name, str(value), 0, 0)
                    if attr:
                        special.append(attr)
                    parsed = True
                    break

            if not parsed:
                # Removed direct check for {attr} here as lxml breaks on it.
                # Handled via preprocessing __pw_sh_.

                # Check for reactive value syntax: attr="{expr}"
                val_str = str(value).strip()
                if (
                    val_str.startswith("{")
                    and val_str.endswith("}")
                    and val_str.count("{") == 1
                ):
                    # Treat as reactive attribute
                    # Exclude special internal attr for spread
                    if name == "__pywire_spread__":
                        special.append(
                            SpreadAttribute(
                                name=name,
                                value=val_str,
                                expr=val_str[3:-1],  # Strip {** and }
                                line=0,
                                column=0,
                            )
                        )
                    else:
                        special.append(
                            ReactiveAttribute(
                                name=name,
                                value=val_str,
                                expr=val_str[1:-1],
                                line=0,
                                column=0,
                            )
                        )
                else:
                    regular[name] = val_str

        return regular, special

    def _looks_like_python_code(self, line: str) -> bool:
        """Check if a line looks like Python code."""
        if not line:
            return False

        # Skip HTML-like lines
        if line.startswith("<") or line.endswith(">"):
            return False

        # Check for common Python patterns
        python_patterns = [
            line.startswith("def "),
            line.startswith("class "),
            line.startswith("import "),
            line.startswith("from "),
            line.startswith("async def "),
            line.startswith("@"),  # Decorators
            # Assignment (but be careful not to match HTML attributes)
            (
                "=" in line
                and not line.strip().startswith("<")
                and ":" not in line[: line.find("=")]
            ),
        ]
        return any(python_patterns)

    def _validate_no_orphaned_python(self, lines: List[str], file_path: str) -> None:
        """Validate that there's no malformed separator or orphaned Python code."""
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue

            if self._separator_re.match(stripped):
                continue

            if self._looks_like_separator_line(stripped):
                raise PyWireSyntaxError(
                    f"Malformed separator on line {i + 1}: '{stripped}'. "
                    "Expected symmetric dashes around 'html', e.g. '---html---'.",
                    file_path=file_path,
                    line=i + 1,
                )

            # Check for Python-like code without proper separator
            # Only check after line 5 to allow for directives at the top
            if i > 5 and self._looks_like_python_code(stripped):
                raise PyWireSyntaxError(
                    f"Python code detected on line {i + 1} without a '---html---' separator. "
                    f"Page-level Python code must appear before the HTML separator.\n"
                    f"Example format:\n"
                    f"  # Python code here\n"
                    f"  ---html---\n"
                    f"  <div>HTML content</div>",
                    file_path=file_path,
                    line=i + 1,
                )
