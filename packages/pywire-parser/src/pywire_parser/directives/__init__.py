"""Directive parsers."""

from pywire_parser.directives.base import DirectiveParser
from pywire_parser.directives.no_spa import NoSpaDirectiveParser
from pywire_parser.directives.path import PathDirectiveParser

__all__ = ["DirectiveParser", "PathDirectiveParser", "NoSpaDirectiveParser"]
