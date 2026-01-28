from typing import Any, AsyncIterator


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


def render_attrs(defined_attrs: dict[str, Any], spread_attrs: dict[str, Any] | None = None) -> str:
    """
    Merge and render HTML attributes.
    defined_attrs: Attributes defined in the template (explicitly).
    spread_attrs: Attributes passed to the component (implicit/explicit spread).
    Rules:
    - spread_attrs override defined_attrs, EXCEPT:
    - class: merged (appended).
    - style: merged (concatenated).
    """
    if not spread_attrs:
        spread_attrs = {}

    # Copy defined_attrs to start
    final_attrs = defined_attrs.copy()

    for k, v in spread_attrs.items():
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
            val = str(v).replace('"', "&quot;")
            parts.append(f' {k}="{val}"')

    return "".join(parts)
