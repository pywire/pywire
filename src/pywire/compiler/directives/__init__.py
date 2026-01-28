"""Directive parsers."""

from pywire.compiler.directives.base import DirectiveParser
from pywire.compiler.directives.no_spa import NoSpaDirectiveParser
from pywire.compiler.directives.path import PathDirectiveParser

__all__ = ["DirectiveParser", "PathDirectiveParser", "NoSpaDirectiveParser"]
