"""Directive code generators."""

from pywire.compiler.codegen.directives.base import DirectiveCodegen
from pywire.compiler.codegen.directives.path import PathDirectiveCodegen

__all__ = ["DirectiveCodegen", "PathDirectiveCodegen"]
