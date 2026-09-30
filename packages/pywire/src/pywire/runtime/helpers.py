import logging
import re
from typing import Any, AsyncIterator

from pywire.runtime.attrs import URL_ATTRS, safe_url

logger = logging.getLogger(__name__)

# An attribute name that can't end the tag or start another attribute
# (Alpine/Vue-style ``@click`` and ``:class`` included).
_ATTR_NAME = re.compile(r"[A-Za-z_:@][A-Za-z0-9_:.@-]*\Z")


async def ensure_async_iterator(iterable: Any) -> AsyncIterator[Any]:
    """
    Ensure an iterable is an async iterator.
    Handles both sync iterables (list, etc.) and async iterables.
    """
    if hasattr(iterable, "__aiter__"):
        async for item in iterable:
            yield item
    elif hasattr(iterable, "__iter__"):
        for item in iterable:
            yield item
    else:
        # Fallback or error?
        # Maybe it's a generator?
        # If it's not iterable at all, standard for loop raises TypeError.
        # We should probably let it raise, or wrapping non-iterable?
        for item in iterable:  # This will raise if not iterable
            yield item


def render_attrs(
    defined_attrs: dict[str, Any], spread_attrs: dict[str, Any] | None = None
) -> str:
    """
    Merge and render HTML attributes.
    defined_attrs: Attributes defined in the template (explicitly).
    spread_attrs: Attributes passed to the component (implicit/explicit spread).
    Rules:
    - spread_attrs override defined_attrs, EXCEPT:
    - class: merged (appended).
    - style: merged (concatenated).

    Spread attributes may come from data, so they are checked: a name that
    isn't a plain attribute name, or is an inline ``on*`` event handler, is
    dropped, and a URL attribute with a script URL is neutralized.
    """
    if not spread_attrs:
        spread_attrs = {}

    # Copy defined_attrs to start
    final_attrs = defined_attrs.copy()

    for k, v in spread_attrs.items():
        k = str(k)
        if not _ATTR_NAME.match(k) or k.lower().startswith("on"):
            logger.warning("Dropped spread attribute %r", k)
            continue
        if (
            k.lower() in URL_ATTRS
            and v is not True
            and v is not False
            and v is not None
        ):
            v = safe_url(k, v)
        if k == "class" and "class" in final_attrs:
            final_attrs["class"] = f"{final_attrs['class']} {v}".strip()
        elif k == "style" and "style" in final_attrs:
            # Naive style merge: concat with semicolon if missing
            s1 = str(final_attrs["style"]).strip()
            s2 = str(v).strip()
            if s1 and not s1.endswith(";"):
                s1 += ";"
            final_attrs["style"] = f"{s1} {s2}".strip()
        else:
            final_attrs[k] = v

    # Render
    parts = []
    for k, v in final_attrs.items():
        if v is True:  # bool attr
            parts.append(f" {k}")
        elif v is False or v is None:
            continue
        else:
            # Escape HTML special characters in attribute values for XSS prevention
            val = (
                str(v)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
            )
            parts.append(f' {k}="{val}"')

    return "".join(parts)
