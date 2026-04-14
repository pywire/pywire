"""Compiler module."""

from pywire.compiler.codegen.generator import CodeGenerator

try:
    from pywire_parser import PyWireParser
except ImportError:
    raise ImportError(
        "pywire-parser is required for compiling .wire files.\n"
        "Install it with: uv add pywire[build]  (or: pip install pywire[build])"
    ) from None

__all__ = ["PyWireParser", "CodeGenerator"]
