"""Interpolation parsers."""

from pywire_parser.interpolation.base import InterpolationParser
from pywire_parser.interpolation.jinja import JinjaInterpolationParser

__all__ = ["InterpolationParser", "JinjaInterpolationParser"]
