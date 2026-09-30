"""The arguments an inline handler call was rendered with.

``{$for item in items}<button @click={delete(item.id)}>`` renders each button
with the value of ``item.id`` for that row. The page signs those values into
the element (``data-pw-args-click``), the client sends the token back with the
event unchanged, and the handler is called with exactly what was signed. A
client can replay a token it was shown, but it cannot change the values or
move them to another handler or page, so it cannot pick an id it was never
given.

Every transport (WebSocket, long-poll, HTTP events, stateless) verifies the
same way and nothing is kept on the server between requests.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from typing import Any, List

# 128-bit tags: a forgery has to guess one.
_TAG_BYTES = 16
# Far above any real argument list; bounds the work a hostile token can cause.
MAX_TOKEN_LEN = 256 * 1024

_process_key = secrets.token_bytes(32)


class HandlerArgsError(ValueError):
    """A client sent arguments the page did not sign for this handler.

    A client error: transports answer it with :data:`REFUSED` (HTTP 400) and
    log a warning, never a traceback.
    """


# What a client is told when its event is refused.
REFUSED = "invalid event arguments"


def _root_page(page: Any) -> Any:
    while getattr(page, "_parent_page", None) is not None:
        page = page._parent_page
    return page


def _key(page: Any) -> bytes:
    """The app's key for handler arguments (``PyWire._handler_args_key``).

    A page rendered outside an app (unit tests) signs with a key of its own
    process.
    """
    try:
        key = _root_page(page).request.app.state.pywire._handler_args_key()
    except (AttributeError, KeyError):
        return _process_key
    return key if isinstance(key, bytes) and key else _process_key


def _scope(page: Any) -> bytes:
    """What makes ``_handler_3`` of one page class differ from another's.

    Compiled pages carry a digest of their generated code, so a token also
    stops working when the code behind the handler changes (a deploy, a hot
    reload).
    """
    cls = type(page)
    scope = getattr(cls, "__pw_scope__", None) or f"{cls.__module__}.{cls.__qualname__}"
    return scope.encode("utf-8")


def _tag(page: Any, handler: str, body: bytes) -> bytes:
    message = b"\0".join((_scope(page), handler.encode("utf-8"), body))
    return hmac.new(_key(page), message, hashlib.sha256).digest()[:_TAG_BYTES]


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_args(page: Any, handler: str, *args: Any) -> str:
    """A token for calling ``handler`` on ``page``'s class with ``args``.

    ``handler`` is the name without a component prefix: the component that
    owns it verifies. The values go through JSON, as they reach the handler.
    """
    body = json.dumps(list(args), separators=(",", ":")).encode("utf-8")
    return f"{_b64(body)}.{_b64(_tag(page, handler, body))}"


def verify_args(page: Any, handler: str, token: Any) -> List[Any]:
    """The arguments ``token`` holds for ``handler``; none when there is none.

    Raises :class:`HandlerArgsError` for anything the page did not sign.
    """
    if not token:
        return []
    if not isinstance(token, str) or len(token) > MAX_TOKEN_LEN:
        raise HandlerArgsError(f"Handler '{handler}': malformed arguments")
    body_text, dot, tag_text = token.partition(".")
    try:
        body, tag = _unb64(body_text), _unb64(tag_text)
    except (binascii.Error, ValueError) as exc:
        raise HandlerArgsError(f"Handler '{handler}': malformed arguments") from exc
    if not dot or not hmac.compare_digest(tag, _tag(page, handler, body)):
        raise HandlerArgsError(
            f"Handler '{handler}': arguments were not rendered for it"
        )
    args = json.loads(body)
    if not isinstance(args, list):
        raise HandlerArgsError(f"Handler '{handler}': malformed arguments")
    return args
