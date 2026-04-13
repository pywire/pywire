"""Main PyWire parser orchestrator."""

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

from pywire_parser.ts_parser import parse as _ts_parse

from pywire_parser.ast_nodes import (
    AwaitAttribute,
    CatchAttribute,
    ElifAttribute,
    ElseAttribute,
    ExceptAttribute,
    FinallyAttribute,
    ForAttribute,
    IfAttribute,
    InterpolationNode,
    ParsedPyWire,
    ReactiveAttribute,
    SpecialAttribute,
    SpreadAttribute,
    TemplateNode,
    ThenAttribute,
    TryAttribute,
)
from pywire_parser.attributes.base import AttributeParser
from pywire_parser.attributes.conditional import ConditionalAttributeParser
from pywire_parser.attributes.events import EventAttributeParser

from pywire_parser.attributes.loop import KeyAttributeParser, LoopAttributeParser
from pywire_parser.directives.base import DirectiveParser
from pywire_parser.directives.layout import LayoutDirectiveParser
from pywire_parser.directives.no_spa import NoSpaDirectiveParser
from pywire_parser.directives.path import PathDirectiveParser
from pywire_parser.exceptions import PyWireSyntaxError
from pywire_parser.interpolation.jinja import JinjaInterpolationParser


@dataclass
class BlockMarkerAttribute(SpecialAttribute):
    """Internal attribute to mark closing blocks like {/if}."""

    keyword: str


class PyWireParser:
    """Main parser orchestrator."""

    def __init__(self) -> None:
        # Directive registry
        self.directive_parsers: List[DirectiveParser] = [
            PathDirectiveParser(),
            NoSpaDirectiveParser(),
            LayoutDirectiveParser(),
        ]

        # Attribute parser chain
        self.attribute_parsers: List[AttributeParser] = [
            EventAttributeParser(),
            ConditionalAttributeParser(),
            LoopAttributeParser(),
            KeyAttributeParser(),
        ]

        # Interpolation parser (pluggable)
        self.interpolation_parser = JinjaInterpolationParser()

    def parse_file(self, file_path: Path) -> ParsedPyWire:
        """Parse a .pywire file."""
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        return self.parse(content, str(file_path))

    def parse(self, content: str, file_path: str = "") -> ParsedPyWire:
        """Parse PyWire content using tree-sitter-pywire."""
        try:
            doc = _ts_parse(content)
        except Exception as e:
            raise PyWireSyntaxError(f"Parser error: {str(e)}", file_path=file_path)

        directives = []
        for d in doc.directives:
            parsed_d = self._map_rust_directive(d, file_path)
            if parsed_d:
                directives.append(parsed_d)

        template_nodes = []
        for n in doc.template:
            template_nodes.append(self._map_node(n))

        # Reconstruct block hierarchy from flat list
        template_nodes = self._structure_hierarchy(template_nodes)

        python_section = doc.python_code
        python_ast = None

        if python_section.strip():
            try:
                from pywire_parser.preprocessor import preprocess_python_code

                preprocessed_code = preprocess_python_code(python_section)
                python_ast = ast.parse(preprocessed_code)
            except SyntaxError as e:
                raise PyWireSyntaxError(
                    f"Python syntax error: {e.msg}",
                    file_path=file_path,
                    line=e.lineno or 1,
                )

        return ParsedPyWire(
            directives=directives,
            template=template_nodes,
            python_code=python_section,
            python_ast=python_ast,
            file_path=file_path,
        )

    def _map_rust_directive(self, d: Any, file_path: str) -> Any:
        """Map a Rust directive to a Directive object."""
        # Use existing directive parsers
        content = d.content if d.content is not None else ""
        line_content = f"!{d.name} {content}".strip()
        for parser in self.directive_parsers:
            if parser.can_parse(line_content):
                return parser.parse(line_content, d.line, d.column)
        return None

    def _map_node(self, rn: Any) -> TemplateNode:
        """Map a Rust ParsedNode to a PyWire TemplateNode."""
        # Clean attributes
        regular_attrs, special_attrs = self._parse_attributes(
            rn.attributes, line=rn.line, col=rn.column
        )

        node = TemplateNode(
            tag=rn.tag,
            attributes=regular_attrs,
            special_attributes=special_attrs,
            line=rn.line,
            column=rn.column,
            is_raw=rn.is_raw,
        )

        if rn.text_content:
            node.text_content = rn.text_content

        if rn.is_block:
            if rn.block_keyword == "interpolation":
                if (
                    not node.special_attributes
                ):  # Avoid duplicate if already parsed by _parse_attributes
                    from pywire_parser.ast_nodes import InterpolationNode

                    node.special_attributes.append(
                        InterpolationNode(
                            expression=(rn.expression or "").strip(),
                            line=rn.line,
                            column=rn.column,
                        )
                    )
            elif rn.block_keyword:
                # Handle control flow tags (if, for, etc.)
                self._handle_rust_block(rn, node)

        # Map children
        for child in rn.children:
            node.children.append(self._map_node(child))

        # Reconstruct block hierarchy for children if any
        if node.children:
            node.children = self._structure_hierarchy(node.children)

        # === Form Validation Schema Extraction ===

        return node

    def _structure_hierarchy(self, nodes: List[TemplateNode]) -> List[TemplateNode]:
        """Convert linear sequence of block/end-block nodes into a tree."""
        roots: List[TemplateNode] = []
        stack: List[TemplateNode] = []

        # Attributes that start a nested block (when tag is None)
        opener_types = (
            IfAttribute,
            ForAttribute,
            TryAttribute,
            AwaitAttribute,
        )

        for node in nodes:
            # Check for closing tag
            is_closing = False
            for attr in node.special_attributes:
                if isinstance(attr, BlockMarkerAttribute):
                    # It's a closing tag (e.g. {/if})
                    is_closing = True
                    break

            if is_closing:
                if stack:
                    block_node = stack.pop()
                    self._validate_block_root(block_node)
                # Discard the closing node itself
                continue

            # Check if this is an opening block
            is_opener = False
            if node.tag is None and node.text_content is None:
                # Check specifics
                for attr in node.special_attributes:
                    if isinstance(attr, opener_types):
                        is_opener = True
                        break

            # Add to current parent or roots
            if stack:
                stack[-1].children.append(node)
            else:
                roots.append(node)

            # If it's an opener, push to stack
            if is_opener:
                stack.append(node)

        return roots

    def _handle_rust_block(self, rn: Any, node: TemplateNode) -> None:
        """Map Rust brace blocks to PyWire special attributes."""
        kw = rn.block_keyword
        if kw.startswith("$"):
            kw = kw[1:]
        elif kw.startswith("/"):
            kw = "/" + kw[1:].lstrip("/")  # Keep one /

        expr = (rn.expression or "").strip()

        if kw.startswith("/"):
            # Closing tag
            node.special_attributes.append(
                BlockMarkerAttribute(
                    name=kw, value="", keyword=kw, line=rn.line, column=rn.column
                )
            )
            return

        if kw == "if":
            node.special_attributes.append(
                IfAttribute(
                    name="$if", value="", condition=expr, line=rn.line, column=rn.column
                )
            )
        elif kw == "elif":
            node.special_attributes.append(
                ElifAttribute(
                    name="$elif",
                    value="",
                    condition=expr,
                    line=rn.line,
                    column=rn.column,
                )
            )
        elif kw == "else":
            node.special_attributes.append(
                ElseAttribute(name="$else", value="", line=rn.line, column=rn.column)
            )
        elif kw == "for":
            # Parse "item in items"
            loop_vars = ""
            iterable = ""
            key_expr = None

            if " in " in expr:
                loop_parts = expr.split(" in ", 1)
                loop_vars = loop_parts[0].strip()
                iterable_part = loop_parts[1].strip()

                if ", key=" in iterable_part:
                    iterable, key_part = iterable_part.rsplit(", key=", 1)
                    key_expr = key_part.strip()
                else:
                    iterable = iterable_part

            node.special_attributes.append(
                ForAttribute(
                    name="$for",
                    value="",
                    is_template_tag=False,
                    loop_vars=loop_vars,
                    iterable=iterable,
                    key=key_expr,
                    line=rn.line,
                    column=rn.column,
                )
            )
        elif kw == "try":
            node.special_attributes.append(
                TryAttribute(name="$try", value="", line=rn.line, column=rn.column)
            )
        elif kw == "except":
            exc_type = expr
            alias = None
            if " as " in expr:
                exc_type, alias = expr.split(" as ", 1)
            node.special_attributes.append(
                ExceptAttribute(
                    name="$except",
                    value="",
                    exception_type=exc_type.strip(),
                    alias=alias.strip() if alias else None,
                    line=rn.line,
                    column=rn.column,
                )
            )
        elif kw == "finally":
            node.special_attributes.append(
                FinallyAttribute(
                    name="$finally", value="", line=rn.line, column=rn.column
                )
            )
        elif kw == "await":
            node.special_attributes.append(
                AwaitAttribute(
                    name="$await",
                    value="",
                    expression=expr,
                    line=rn.line,
                    column=rn.column,
                )
            )
        elif kw == "then":
            node.special_attributes.append(
                ThenAttribute(
                    name="$then",
                    value="",
                    variable=expr.strip() if expr else None,
                    line=rn.line,
                    column=rn.column,
                )
            )
        elif kw == "catch":
            node.special_attributes.append(
                CatchAttribute(
                    name="$catch",
                    value="",
                    variable=expr.strip() if expr else None,
                    line=rn.line,
                    column=rn.column,
                )
            )
        elif kw == "html":
            from pywire_parser.ast_nodes import InterpolationNode

            node.special_attributes.append(
                InterpolationNode(
                    expression=expr, is_raw=True, line=rn.line, column=rn.column
                )
            )

    def _validate_block_root(self, node: TemplateNode) -> None:
        """Validate that certain blocks have only one root element."""
        from pywire_parser.ast_nodes import (
            ForAttribute,
            ElseAttribute,
            ElifAttribute,
        )

        for_attrs = [a for a in node.special_attributes if isinstance(a, ForAttribute)]
        if for_attrs:
            for_attr = for_attrs[0]
            if not for_attr.key:
                real_children = []
                for c in node.children:
                    if any(
                        isinstance(a, (ElseAttribute, ElifAttribute))
                        for a in c.special_attributes
                    ):
                        break

                    is_real = False
                    if c.tag:
                        is_real = True
                    elif c.text_content and c.text_content.strip():
                        is_real = True
                    elif any(
                        not isinstance(a, BlockMarkerAttribute)
                        for a in c.special_attributes
                    ):
                        is_real = True

                    if is_real:
                        real_children.append(c)

                print(
                    f"[DEBUG-PARSER] Validating For block at line {node.line}. Children: {len(node.children)}, Real: {len(real_children)}"
                )
                for i, c in enumerate(real_children):
                    print(
                        f"  Real Child {i}: tag={c.tag}, text={c.text_content[:20] if c.text_content else None}"
                    )

                if len(real_children) != 1:
                    from pywire_parser.exceptions import PyWireSyntaxError

                    raise PyWireSyntaxError(
                        "A $for loop without a 'key' must have exactly one root element",
                        line=node.line,
                    )

    def _parse_text(
        self, text: str, start_line: int = 0, raw_text: bool = False, start_col: int = 0
    ) -> List[TemplateNode]:
        """Helper to parse text string into list of text/interpolation nodes."""
        if not text:
            return []

        if raw_text:
            # Bypass interpolation for raw text elements (script, style)
            return [
                TemplateNode(
                    tag=None,
                    text_content=text,
                    line=start_line,
                    column=start_col,
                    is_raw=True,
                )
            ]

        parts = self.interpolation_parser.parse(text, line=start_line, col=start_col)
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

    def _parse_attributes(
        self, attrs: Dict[str, Any], line: int = 0, col: int = 0
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

            elif name == "$permanent":
                regular["data-pw-permanent"] = "true"
                continue
            elif name == "$reload":
                regular["data-pw-reload"] = "true"
                continue

            if value is None:
                value = ""

            parsed = False
            for parser in self.attribute_parsers:
                if parser.can_parse(name):
                    attr = parser.parse(name, str(value), line, col)
                    if attr:
                        special.append(attr)
                    parsed = True
                    break

            if not parsed:
                # Removed direct check for {attr} here as lxml breaks on it.
                # Handled via preprocessing __pw_sh_.

                # Check for reactive value syntax: attr="{expr}"
                val_str = str(value).strip()
                if val_str.startswith("{") and val_str.endswith("}"):
                    # Treat as reactive attribute
                    # Exclude special internal attr for spread
                    if name == "__pywire_spread__":
                        # Spread attributes {**props}
                        special.append(
                            SpreadAttribute(
                                name=name,
                                value=val_str,
                                expr=val_str[3:-1].strip(),  # Strip {** and }
                                line=line,
                                column=col,
                            )
                        )
                    elif name.startswith("__pw_sh_"):
                        # Shorthand attributes {attr}
                        real_name = name[8:]
                        special.append(
                            ReactiveAttribute(
                                name=real_name,
                                value=val_str,
                                expr=val_str[1:-1].strip(),  # Strip { and }
                                line=line,
                                column=col,
                            )
                        )
                    else:
                        special.append(
                            ReactiveAttribute(
                                name=name,
                                value=val_str,
                                expr=val_str[1:-1],
                                line=line,
                                column=col,
                            )
                        )
                else:
                    regular[name] = val_str

        return regular, special
