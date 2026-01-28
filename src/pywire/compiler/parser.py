"""Main PyWire parser orchestrator."""

import ast
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

from lxml import html  # type: ignore

from pywire.compiler.ast_nodes import (
    EventAttribute,
    FieldValidationRules,
    FormValidationSchema,
    InterpolationNode,
    ModelAttribute,
    ParsedPyWire,
    ReactiveAttribute,
    SpecialAttribute,
    SpreadAttribute,
    TemplateNode,
)
from pywire.compiler.attributes.base import AttributeParser
from pywire.compiler.attributes.bind import BindAttributeParser
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
            BindAttributeParser(),
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
        lines = content.split("\n")

        # Split into sections: directives/template and Python code
        python_start = -1
        python_end = -1

        for i, line in enumerate(lines):
            if line.strip() == "---":
                if python_start == -1:
                    python_start = i
                else:
                    python_end = i
                    break

        python_section = ""
        template_tail = []

        if python_start >= 0 and python_end > python_start:
            # Valid block: --- ... ---
            directive_section = "\n".join(lines[:python_start])
            python_section = "\n".join(lines[python_start + 1 : python_end])
            template_tail = lines[python_end + 1 :]
        elif python_start >= 0:
            # Unclosed block - treat everything after as Python?
            # Or error? Let's assume everything after is Python (legacy behavior somewhat)
            # But this swallows template.
            # For now, let's keep it consistent: everything before is directives.
            directive_section = "\n".join(lines[:python_start])
            python_section = "\n".join(lines[python_start + 1 :])
        else:
            # No block - validate that there's no malformed separator or orphaned Python code
            self._validate_no_orphaned_python(lines, file_path)
            directive_section = content
            python_section = ""

        # Parse directives (handles multiline directives by accumulating lines)
        directives = []
        template_lines = []
        directive_lines = directive_section.split("\n")

        directives_done = False  # Enforce directives at top

        i = 0
        while i < len(directive_lines):
            old_i = i
            line = directive_lines[i]
            line_stripped = line.strip()
            line_num = i + 1

            if not line_stripped or line_stripped.startswith("---"):
                # Blank lines are fine, keep them in template for lining up
                # (or ignore? if we want correct line numbers for template,
                # we need them)
                # But if we are still parsing directives, blank lines are ignored.
                # If we are done directives, they become template blank lines.
                if directives_done:
                    template_lines.append(line)
                else:
                    # In directive section, blank lines don't matter?
                    # Actually we need to PAD template_lines to keep sync if we skip them here?
                    # "Add blank lines to template_lines to preserve line numbers"
                    # logic below handles it.
                    pass
                i += 1
                continue

            # Check if it's a directive
            found_directive = False

            if not directives_done:
                for parser in self.directive_parsers:
                    if parser.can_parse(line_stripped):
                        # Try single line first
                        directive = parser.parse(line_stripped, line_num, 0)
                        if directive:
                            directives.append(directive)
                            found_directive = True
                            i += 1
                            break

                        # If single line failed, try accumulating multiline content
                        # Count open braces/brackets/PARENS to find the end
                        accumulated = line_stripped
                        brace_count = accumulated.count("{") - accumulated.count("}")
                        bracket_count = accumulated.count("[") - accumulated.count("]")
                        paren_count = accumulated.count("(") - accumulated.count(")")

                        j = i + 1

                        while (brace_count > 0 or bracket_count > 0 or paren_count > 0) and j < len(
                            directive_lines
                        ):
                            next_line = directive_lines[j].strip()
                            accumulated += "\n" + next_line
                            brace_count += next_line.count("{") - next_line.count("}")
                            bracket_count += next_line.count("[") - next_line.count("]")
                            paren_count += next_line.count("(") - next_line.count(")")
                            j += 1

                        # Try parsing the accumulated content
                        directive = parser.parse(accumulated, line_num, 0)
                        if directive:
                            directives.append(directive)
                            found_directive = True
                            i = j  # Skip past all accumulated lines
                            break
                        else:
                            i += 1  # Parse failed, move on to this line being template?
                        break

            if found_directive:
                # Add blank lines to template_lines to preserve line numbers
                # We skipped from old_i to i.
                # old_i was the line where we started looking.
                # i is now the next line to process.
                # So lines [old_i : i] were directives.
                for _ in range(i - old_i):
                    template_lines.append("")
            else:
                # Not a directive, part of template
                directives_done = True  # Once we hit template, no more directives allowed

                # Check if this line LOOKS like a directive but wasn't parsed
                # (e.g. invalid syntax or misplaced)
                if line_stripped.startswith("!"):
                    # Could be a warning or error?
                    pass

                template_lines.append(line)
                i += 1

        # Append template content that followed the Python block
        if template_tail:
            template_lines.extend(template_tail)

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
                python_ast = ast.parse(python_section)
            except SyntaxError as e:
                # Calculate correct line number
                # python_start is 0-indexed line number of '---'
                # e.lineno is 1-indexed relative to python_section
                # actual_line = (python_start + 1) + e.lineno
                line_offset = python_start + 1
                actual_line = line_offset + (e.lineno or 1)

                raise PyWireSyntaxError(
                    f"Python syntax error: {e.msg}", file_path=file_path, line=actual_line
                )

        if python_ast:
            # Shift line numbers to match original file
            # python_start is index of '---' line
            # python_section code starts at python_start + 1
            # Current AST lines start at 1.
            # We want line 1 to map to (python_start + 1) + 1 = python_start + 2
            # So offset = python_start + 1
            ast.increment_lineno(python_ast, python_start + 1)

        return ParsedPyWire(
            directives=directives,
            template=template_nodes,
            python_code=python_section,
            python_ast=python_ast,
            file_path=file_path,
        )

    def _parse_text(
        self, text: str, start_line: int = 0, raw_text: bool = False
    ) -> List[TemplateNode]:
        """Helper to parse text string into list of text/interpolation nodes."""
        if not text:
            return []

        if raw_text:
            # Bypass interpolation for raw text elements (script, style)
            return [
                TemplateNode(tag=None, text_content=text, line=start_line, column=0, is_raw=True)
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
                        TemplateNode(tag=None, text_content=part, line=start_line, column=0)
                    )
            else:
                node = TemplateNode(tag=None, text_content=None, line=part.line, column=part.column)
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
            is_raw = isinstance(element.tag, str) and element.tag.lower() in ("script", "style")
            text_nodes = self._parse_text(
                element.text, start_line=getattr(element, "sourceline", 0), raw_text=is_raw
            )
            if text_nodes:
                node.children.extend(text_nodes)

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

    def _extract_form_validation_schema(self, form_node: TemplateNode) -> FormValidationSchema:
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

    def _extract_field_rules(self, node: TemplateNode, field_name: str) -> FieldValidationRules:
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
                # Check for reactive value syntax: attr="{expr}"
                val_str = str(value).strip()
                if val_str.startswith("{") and val_str.endswith("}") and val_str.count("{") == 1:
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
                                name=name, value=val_str, expr=val_str[1:-1], line=0, column=0
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

            # Check for partial separator patterns
            if stripped and all(c == "-" for c in stripped) and stripped != "---":
                raise PyWireSyntaxError(
                    f"Malformed separator on line {i + 1}: found '{stripped}' but expected '---'. "
                    f"Page-level Python code must be enclosed between two '---' lines.",
                    file_path=file_path,
                    line=i + 1,
                )

            # Check for Python-like code without proper separator
            # Only check after line 5 to allow for directives at the top
            if i > 5 and self._looks_like_python_code(stripped):
                raise PyWireSyntaxError(
                    f"Python code detected on line {i + 1} without '---' separator. "
                    f"Page-level Python code must be enclosed between two '---' lines.\n"
                    f"Example format:\n"
                    f"  <div>HTML content</div>\n"
                    f"  ---\n"
                    f"  # Python code here\n"
                    f"  ---",
                    file_path=file_path,
                    line=i + 1,
                )
