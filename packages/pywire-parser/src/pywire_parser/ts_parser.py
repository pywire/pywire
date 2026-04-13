"""Tree-sitter based parser for .wire files.

This is a pure-Python port of the Rust parser (rust/lib.rs) using py-tree-sitter
and tree-sitter-pywire. It produces the same ParsedDocument/ParsedNode/ParsedDirective
dataclasses that the rest of the compiler pipeline consumes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import tree_sitter_pywire as tspywire
from tree_sitter import Language, Node, Parser

PYWIRE_LANGUAGE = Language(tspywire.language())

# Node kinds that are mapped as template children
_TEMPLATE_KINDS = frozenset(
    {
        "tag",
        "self_closing_tag",
        "void_tag",
        "script_tag",
        "style_tag",
        "text",
        "interpolation",
        "brace_block",
        "end_brace_block",
        "doctype",
        "hyphen",
        "bang",
    }
)

# Node kinds that recurse as children of a tag
_CHILD_KINDS = frozenset(
    {
        "tag",
        "self_closing_tag",
        "void_tag",
        "script_tag",
        "style_tag",
        "text",
        "interpolation",
        "brace_block",
        "end_brace_block",
        "ERROR",
        "hyphen",
        "bang",
        "comment",
    }
)


@dataclass
class ParsedDirective:
    name: str
    content: Optional[str]
    line: int
    column: int


@dataclass
class ParsedNode:
    tag: Optional[str] = None
    is_block: bool = False
    block_keyword: Optional[str] = None
    text_content: Optional[str] = None
    expression: Optional[str] = None
    attributes: Dict[str, Optional[str]] = field(default_factory=dict)
    children: List["ParsedNode"] = field(default_factory=list)
    line: int = 0
    column: int = 0
    is_raw: bool = False


@dataclass
class ParsedDocument:
    directives: List[ParsedDirective]
    python_code: str
    template: List[ParsedNode]


def _get_text(source: bytes, node: Node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8")


def _map_directive(source: bytes, node: Node) -> ParsedDirective:
    text = _get_text(source, node).strip()

    # Name starts after '!' and ends at first non-word char
    name_part_full = text[1:] if text.startswith("!") else text
    name_end = 0
    for i, ch in enumerate(name_part_full):
        if not (ch.isalnum() or ch == "_"):
            name_end = i
            break
    else:
        name_end = len(name_part_full)

    name = name_part_full[:name_end]
    content_part = name_part_full[name_end:].strip()
    content = content_part if content_part else None

    row, col = node.start_point
    return ParsedDirective(name=name, content=content, line=row + 1, column=col)


def _map_node(source: bytes, node: Node) -> ParsedNode:
    tag = None
    is_block = False
    block_keyword = None
    text_content = None
    expression = None
    attributes: Dict[str, Optional[str]] = {}
    children: List[ParsedNode] = []

    row, col = node.start_point
    line = row + 1
    column = col
    is_raw = False

    kind = node.type

    if kind in ("tag", "self_closing_tag", "void_tag", "script_tag", "style_tag"):
        # Extract tag name
        name_node = node.child_by_field_name("name")
        if name_node:
            tag = _get_text(source, name_node)
        else:
            start_node = node.child_by_field_name("start_tag")
            if start_node:
                text = _get_text(source, start_node)
                if text.startswith("<"):
                    tag = text[1:]
            elif kind == "script_tag":
                tag = "script"
            elif kind == "style_tag":
                tag = "style"

        is_raw_tag = kind in ("script_tag", "style_tag")
        if is_raw_tag:
            # Extract raw text content between opening and closing tags
            node_source = _get_text(source, node)
            lower = node_source.lower()

            closing_tag = "</script>" if kind == "script_tag" else "</style>"
            open_end = node_source.find(">")
            close_start = lower.rfind(closing_tag)

            if (
                open_end is not None
                and close_start is not None
                and open_end >= 0
                and close_start >= 0
            ):
                start_rel = open_end + 1
                if close_start >= start_rel:
                    raw_text = node_source[start_rel:close_start]
                    if raw_text:
                        children.append(
                            ParsedNode(
                                text_content=raw_text,
                                line=line,
                                column=column,
                                is_raw=True,
                            )
                        )

        # Process child nodes
        cursor = node.walk()
        if cursor.goto_first_child():
            while True:
                child = cursor.node
                child_kind = child.type

                if child_kind == "attribute":
                    is_shorthand = False
                    attr_cursor = child.walk()
                    if attr_cursor.goto_first_child():
                        while True:
                            attr_child = attr_cursor.node
                            k = attr_child.type

                            if k == "attribute_shorthand":
                                text = _get_text(source, attr_child)
                                if text.startswith("{**"):
                                    attributes["__pywire_spread__"] = text
                                else:
                                    inner = text[1:-1].strip()
                                    attributes[f"__pw_sh_{inner}"] = text
                                is_shorthand = True
                                break
                            elif k == "spread_shorthand":
                                text = _get_text(source, attr_child)
                                attributes["__pywire_spread__"] = text
                                is_shorthand = True
                                break

                            if not attr_cursor.goto_next_sibling():
                                break

                    if not is_shorthand:
                        attr_name = ""
                        attr_value = None
                        name_n = child.child_by_field_name("name")
                        if name_n:
                            attr_name = _get_text(source, name_n)
                        value_n = child.child_by_field_name("value")
                        if value_n:
                            text = _get_text(source, value_n)
                            if (text.startswith('"') and text.endswith('"')) or (
                                text.startswith("'") and text.endswith("'")
                            ):
                                attr_value = text[1:-1]
                            else:
                                attr_value = text
                        attributes[attr_name] = attr_value

                elif not is_raw_tag and child_kind in _CHILD_KINDS:
                    children.append(_map_node(source, child))

                if not cursor.goto_next_sibling():
                    break

    elif kind == "brace_block":
        is_block = True
        kw_node = node.child_by_field_name("keyword")
        if kw_node:
            block_keyword = _get_text(source, kw_node)
        expr_node = node.child_by_field_name("expression")
        if expr_node:
            expression = _get_text(source, expr_node)

    elif kind == "end_brace_block":
        is_block = True
        name_node = node.child_by_field_name("name")
        if name_node:
            block_keyword = f"/{_get_text(source, name_node)}"

    elif kind == "interpolation":
        is_block = True
        block_keyword = "interpolation"
        expr_node = node.child_by_field_name("expr")
        if expr_node:
            expression = _get_text(source, expr_node)

    elif kind in ("text", "python_line", "hyphen", "bang"):
        text_content = _get_text(source, node)

    elif kind == "ERROR":
        text_content = _get_text(source, node)

    return ParsedNode(
        tag=tag,
        is_block=is_block,
        block_keyword=block_keyword,
        text_content=text_content,
        expression=expression,
        attributes=attributes,
        children=children,
        line=line,
        column=column,
        is_raw=is_raw,
    )


def parse(source: str) -> ParsedDocument:
    """Parse a .wire file source string into a ParsedDocument.

    This is the main entry point, equivalent to the Rust `parse()` function.
    """
    parser = Parser(PYWIRE_LANGUAGE)
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    root = tree.root_node

    directives: List[ParsedDirective] = []
    python_code = ""
    template: List[ParsedNode] = []

    cursor = root.walk()
    if cursor.goto_first_child():
        while True:
            child = cursor.node
            kind = child.type

            if kind == "directives_section":
                dir_cursor = child.walk()
                if dir_cursor.goto_first_child():
                    while True:
                        directives.append(_map_directive(source_bytes, dir_cursor.node))
                        if not dir_cursor.goto_next_sibling():
                            break

            elif kind == "frontmatter":
                content_node = child.child_by_field_name("python_content")
                if content_node:
                    python_code += _get_text(source_bytes, content_node)
                else:
                    # Fallback: check children for python_content node
                    fm_cursor = child.walk()
                    if fm_cursor.goto_first_child():
                        while True:
                            if fm_cursor.node.type == "python_content":
                                python_code += _get_text(source_bytes, fm_cursor.node)
                            if not fm_cursor.goto_next_sibling():
                                break

            elif kind == "template_section":
                t_cursor = child.walk()
                if t_cursor.goto_first_child():
                    while True:
                        t_node = t_cursor.node
                        if t_node.type in _TEMPLATE_KINDS:
                            template.append(_map_node(source_bytes, t_node))
                        if not t_cursor.goto_next_sibling():
                            break

            if not cursor.goto_next_sibling():
                break

    return ParsedDocument(
        directives=directives,
        python_code=python_code,
        template=template,
    )


def version() -> str:
    return "0.3.0-python"
