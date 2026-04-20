"""PyWire parser — shared parsing library for .wire files.

Used by pywire (core framework) and pywire-language-server.
"""

from pywire_parser.parser import PyWireParser
from pywire_parser.ts_parser import parse
from pywire_parser.ast_nodes import (
    AuthAttribute,
    Directive,
    InterpolationNode,
    ParsedPyWire,
    SpecialAttribute,
    TemplateNode,
)
from pywire_parser.exceptions import PyWireSyntaxError

__all__ = [
    "PyWireParser",
    "parse",
    "AuthAttribute",
    "Directive",
    "InterpolationNode",
    "ParsedPyWire",
    "PyWireSyntaxError",
    "SpecialAttribute",
    "TemplateNode",
]
