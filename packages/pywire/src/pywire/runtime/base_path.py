"""Serving a PyWire app under a URL prefix.

An app can live below the site root in two ways:

- **Mounted** in a host app (``Mount("/app", pywire)``) or behind a server
  started with ``--root-path``. The prefix arrives as the ASGI
  ``root_path`` and nothing needs configuring.
- **Behind a proxy that strips the prefix** (a Cloudflare Worker route, an
  nginx ``location``). The app never sees the prefix, so it is configured
  with ``PyWire(base_path="/demo")``. ``base_path`` goes in front of any
  ``root_path`` that arrives, so it also composes with mounting.

Either way the app is written as if it ran at ``/``: page routes, root-
relative links, redirects and cookie paths are all relative to the prefix,
and PyWire adds the prefix on the way out. A URL that already starts with
the prefix is left alone, so apps that spelled the prefix out by hand keep
working.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List, MutableMapping, Optional, Tuple

#: Attribute that stops PyWire from adding the prefix to one element's URLs,
#: for links that point outside the app on the same site.
NO_BASE_ATTR = "data-pw-no-base"

# Attributes whose value is a single URL.
_URL_ATTRS = frozenset({"href", "src", "action", "formaction", "poster", "xlink:href"})
# Attributes whose value is a srcset (``url [descriptor], url [descriptor]``).
_SRCSET_ATTRS = frozenset({"srcset", "imagesrcset"})

# Elements whose content is raw text: never parsed for tags.
_RAW_TEXT_ELEMENTS = frozenset({"script", "style", "textarea", "title"})

# A comment, or a start tag. Quoted attribute values may contain ``>``.
_TOKEN_RE = re.compile(
    r"<!--.*?-->|<(?P<name>[a-zA-Z][^\s/>]*)(?P<attrs>(?:\"[^\"]*\"|'[^']*'|[^'\">])*)>",
    re.DOTALL,
)
_ATTR_RE = re.compile(
    r"(?P<lead>\s)(?P<name>[^\s\"'>/=]+)"
    r"(?:(?P<eq>\s*=\s*)(?:\"(?P<dq>[^\"]*)\"|'(?P<sq>[^']*)'|(?P<uq>[^\s\"'>]+)))?"
)


def normalize_base_path(value: Optional[str]) -> str:
    """Return ``value`` as ``""`` or ``/segment[/segment...]``.

    Accepts ``None``, ``""`` and ``"/"`` for "no prefix", and tolerates a
    missing leading or a trailing slash.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("base_path must be a string")
    stripped = value.strip().strip("/")
    if not stripped:
        return ""
    if any(ch in stripped for ch in "?#\\") or "//" in stripped:
        raise ValueError(f"base_path must be a plain path like '/demo', got {value!r}")
    return "/" + stripped


def _is_under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def prefix_of(scope: Optional[MutableMapping[str, Any]]) -> str:
    """The public URL prefix for a request or WebSocket scope."""
    if not scope:
        return ""
    root = scope.get("root_path") or ""
    return root.rstrip("/") if isinstance(root, str) else ""


def with_base(url: Any, prefix: str) -> Any:
    """Put ``prefix`` in front of a root-relative URL.

    Absolute (``https://…``), protocol-relative (``//host``), relative
    (``page``, ``?q``, ``#top``) and already-prefixed URLs are returned as
    they are. Non-strings pass through untouched.
    """
    if not prefix or not isinstance(url, str):
        return url
    if not url.startswith("/") or url.startswith("//"):
        return url
    path_end = len(url)
    for sep in ("?", "#"):
        idx = url.find(sep)
        if idx != -1:
            path_end = min(path_end, idx)
    if _is_under(url[:path_end], prefix):
        return url
    return prefix + url


def cookie_path(path: Optional[str], prefix: str) -> Optional[str]:
    """Scope a cookie ``Path`` to the app: ``/`` becomes the prefix itself."""
    if not prefix or not isinstance(path, str) or not path.startswith("/"):
        return path
    if _is_under(path, prefix):
        return path
    if path == "/":
        return prefix
    return prefix + path


def strip_base(path: str, prefix: str) -> str:
    """Turn a browser path into the app-relative path the router matches."""
    if not prefix or not isinstance(path, str):
        return path
    if path == prefix:
        return "/"
    if path.startswith(prefix + "/"):
        return path[len(prefix) :]
    return path


def apply_base_path(scope: Any, base: str) -> Any:
    """Return ``scope`` with ``base`` in front of its ``root_path``.

    Keeps the ASGI rule that ``path`` includes ``root_path``, whether or not
    the proxy in front stripped ``base`` from the path. The caller's scope
    is not modified.
    """
    if not base or scope.get("type") not in ("http", "websocket"):
        return scope
    root = scope.get("root_path") or ""
    if _is_under(root, base):
        return scope

    path: str = scope.get("path") or "/"
    raw_path = scope.get("raw_path")
    # Servers that predate the ASGI rule send ``path`` without ``root_path``.
    if root and not _is_under(path, root):
        path = root + path
        if isinstance(raw_path, bytes):
            raw_path = root.encode("latin-1") + raw_path

    new_root = base + root
    new_scope = dict(scope)
    new_scope["root_path"] = new_root
    if not _is_under(path, new_root):
        # The proxy stripped ``base``; put it back.
        new_scope["path"] = base + path
        if isinstance(raw_path, bytes):
            new_scope["raw_path"] = base.encode("latin-1") + raw_path
    app_root = scope.get("app_root_path")
    if isinstance(app_root, str) and not _is_under(app_root, base):
        new_scope["app_root_path"] = base + app_root
    return new_scope


def rewrite_headers(
    headers: Iterable[Tuple[bytes, bytes]], prefix: str
) -> List[Tuple[bytes, bytes]]:
    """Prefix root-relative ``Location`` headers and ``Set-Cookie`` paths."""
    out: List[Tuple[bytes, bytes]] = []
    for name, value in headers:
        lname = name.lower()
        if lname == b"location":
            loc = value.decode("latin-1")
            value = with_base(loc, prefix).encode("latin-1")
        elif lname == b"set-cookie":
            value = _rewrite_set_cookie(value.decode("latin-1"), prefix).encode(
                "latin-1"
            )
        out.append((name, value))
    return out


def _rewrite_set_cookie(header: str, prefix: str) -> str:
    parts = header.split(";")
    has_path = False
    for i, part in enumerate(parts[1:], start=1):
        key, sep, val = part.strip().partition("=")
        if key.lower() == "path" and sep:
            has_path = True
            new = cookie_path(val.strip(), prefix)
            if new != val.strip():
                parts[i] = f" {key}={new}"
    if not has_path:
        # No Path: browsers default it to the request's directory, which
        # varies by page. Pin it to the app.
        parts.append(f" Path={prefix}")
    return ";".join(parts)


def _rewrite_srcset(value: str, prefix: str) -> str:
    candidates = []
    for candidate in value.split(","):
        stripped = candidate.strip()
        if not stripped:
            candidates.append(candidate)
            continue
        url, sep, descriptor = stripped.partition(" ")
        candidates.append(with_base(url, prefix) + (sep + descriptor if sep else ""))
    return ", ".join(candidates)


def _rewrite_attrs(attrs: str, prefix: str) -> str:
    if NO_BASE_ATTR in attrs:
        return attrs

    def repl(m: "re.Match[str]") -> str:
        if m.group("eq") is None:
            return m.group(0)
        name = m.group("name").lower()
        if name in _URL_ATTRS:
            fn = with_base
        elif name in _SRCSET_ATTRS:
            fn = _rewrite_srcset
        else:
            return m.group(0)
        for group, quote in (("dq", '"'), ("sq", "'"), ("uq", "")):
            val = m.group(group)
            if val is not None:
                new = fn(val, prefix)
                if new == val:
                    return m.group(0)
                return f"{m.group('lead')}{m.group('name')}{m.group('eq')}{quote}{new}{quote}"
        return m.group(0)

    return _ATTR_RE.sub(repl, attrs)


def rewrite_html(html: str, prefix: str) -> str:
    """Prefix root-relative URLs in ``href``, ``src``, ``action`` and friends.

    Script, style, textarea and title contents and comments are copied as
    they are. Elements carrying ``data-pw-no-base`` are skipped.
    """
    if not prefix or not html or "/" not in html:
        return html
    out: List[str] = []
    pos = 0
    n = len(html)
    while pos < n:
        m = _TOKEN_RE.search(html, pos)
        if m is None:
            break
        out.append(html[pos : m.start()])
        name = m.group("name")
        if name is None:  # comment
            out.append(m.group(0))
            pos = m.end()
            continue
        attrs = m.group("attrs") or ""
        out.append(f"<{name}{_rewrite_attrs(attrs, prefix)}>")
        pos = m.end()
        if name.lower() in _RAW_TEXT_ELEMENTS:
            close = re.compile(rf"</{re.escape(name)}\s*>", re.IGNORECASE)
            end = close.search(html, pos)
            stop = end.start() if end else n
            out.append(html[pos:stop])
            pos = stop
    out.append(html[pos:])
    return "".join(out)


class BasePathHeaders:
    """ASGI wrapper that applies :func:`rewrite_headers` to HTTP responses."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        prefix = prefix_of(scope) if scope.get("type") == "http" else ""
        if not prefix:
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Any) -> None:
            if message.get("type") == "http.response.start":
                message = dict(message)
                message["headers"] = rewrite_headers(
                    message.get("headers") or [], prefix
                )
            await send(message)

        await self.app(scope, receive, send_wrapper)
