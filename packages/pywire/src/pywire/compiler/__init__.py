"""Compiler module."""

# Check parser presence first — the codegen import chain pulls in
# pywire.compiler.* re-export shims which themselves require
# pywire_parser. Without this guard, missing pywire-parser would
# surface as a cryptic ModuleNotFoundError deep in codegen.
try:
    from pywire_parser import PyWireParser
except ImportError:
    raise ImportError(
        "pywire-parser is required for compiling .wire files.\n"
        "Install it with: uv add pywire[build]  (or: pip install 'pywire[build]')"
    ) from None

from pywire.compiler.codegen.generator import CodeGenerator

__all__ = ["PyWireParser", "CodeGenerator"]
