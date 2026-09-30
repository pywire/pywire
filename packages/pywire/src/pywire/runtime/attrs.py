"""Runtime helpers for attribute values computed at render time.

Used by codegen for every ``attr={expr}`` binding and by ``render_attrs`` for
spread attributes. ``class`` and ``style`` accept a list, tuple, dict, or
string; URL attributes refuse script schemes; everything else is
``str(value)``. Values are HTML-escaped later, when the tag is written.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Attributes whose value the browser loads or navigates to.
URL_ATTRS = frozenset(
    {
        "action",
        "background",
        "cite",
        "codebase",
        "data",
        "formaction",
        "href",
        "manifest",
        "ping",
        "poster",
        "src",
        "xlink:href",
    }
)
# Navigations and form targets: a data: URL there is a document the user can
# be sent to (a phishing page, script in some browsers). An <img src> may be
# a data: image.
_NAVIGATION_ATTRS = frozenset({"action", "formaction", "href", "xlink:href"})
# Browsers drop these anywhere in a URL before reading its scheme.
_URL_NOISE = re.compile(r"[\x00-\x20\x7f]+")
BLOCKED_URL = "about:invalid#blocked"

# A style declaration from a dict: a property name, and a value that can't
# end the declaration, load a resource or run script.
_CSS_PROPERTY = re.compile(r"-{0,2}[A-Za-z][A-Za-z0-9-]*\Z")
_CSS_UNSAFE_VALUE = re.compile(
    r"[;{}<>\\]|url\s*\(|image-set\s*\(|expression\s*\(|javascript:|@import",
    re.IGNORECASE,
)


def safe_url(name: str, value: Any) -> str:
    """``value`` unless it would run script (or open a data: document).

    A URL a template builds from data (``href={link}``) that turns out to be
    ``javascript:...`` renders as ``about:invalid#blocked`` instead.
    """
    text = str(value)
    scheme = _URL_NOISE.sub("", text).lower().partition(":")
    blocked = ("javascript", "vbscript")
    if name.lower() in _NAVIGATION_ATTRS:
        blocked += ("data",)
    if scheme[1] and scheme[0] in blocked:
        logger.warning("Blocked a %s: URL in %s=", scheme[0], name)
        return BLOCKED_URL
    return text


def _normalize_class(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(str(k) for k, v in value.items() if v)
    if isinstance(value, (list, tuple, set)):
        return " ".join(str(item) for item in value if item)
    return str(value)


def _normalize_style(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            if v is None or v is False:
                continue
            prop, text = str(k), str(v)
            if not _CSS_PROPERTY.match(prop) or _CSS_UNSAFE_VALUE.search(text):
                logger.warning("Dropped unsafe style declaration %r", prop)
                continue
            parts.append(f"{prop}:{text}")
        return ";".join(parts)
    return str(value)


def normalize_attr(name: str, value: Any) -> str:
    """Render a computed attribute value as a string.

    Special handling:
    - ``class``: list/tuple/set → space-joined truthy items;
      dict → space-joined keys whose values are truthy.
    - ``style``: dict → ``;``-joined ``k:v`` pairs (skips None/False, and
      drops a declaration whose name isn't a CSS property or whose value
      could end it or load or run something: ``;``, braces, ``url(``,
      ``expression(``, ``javascript:``). Write such a style as a string.
    - URL attributes (``href``, ``src``, ``action``, ...): see :func:`safe_url`.
    - Anything else: ``str(value)``.
    """
    if name == "class":
        return _normalize_class(value)
    if name == "style":
        return _normalize_style(value)
    if name.lower() in URL_ATTRS:
        return safe_url(name, value)
    return str(value)
