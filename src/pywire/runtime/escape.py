"""HTML escaping utilities for XSS prevention."""

from typing import Any


def escape_html(value: Any) -> str:
    """Escape HTML special characters to prevent XSS.

    Escapes: & < > "

    Args:
        value: Any value to escape (will be converted to string first)

    Returns:
        HTML-escaped string safe for embedding in HTML content
    """
    s = str(value)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
