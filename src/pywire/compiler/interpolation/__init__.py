"""Interpolation parsers."""

from pywire.compiler.interpolation.base import InterpolationParser
from pywire.compiler.interpolation.jinja import JinjaInterpolationParser

__all__ = ["InterpolationParser", "JinjaInterpolationParser"]
