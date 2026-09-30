"""What makes a secret key good enough to sign or encrypt with."""

from __future__ import annotations

from typing import Optional, Union

MIN_SECRET_BYTES = 32
# Fewer distinct characters than this is a pattern, not randomness: 32 random
# hex digits have about 13, a password manager's output far more.
_MIN_DISTINCT = 8
# Values copied from docs and templates instead of generated.
_PLACEHOLDERS = (
    "changeme",
    "change-me",
    "change_me",
    "replaceme",
    "replace-me",
    "replace_me",
    "your-secret",
    "your_secret",
    "yoursecret",
    "insecure",
    "placeholder",
)
GENERATE_HINT = (
    "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
)


def weak_secret(secret: Union[str, bytes]) -> Optional[str]:
    """Why ``secret`` is too weak to use, or None when it will do."""
    raw = secret.encode("utf-8") if isinstance(secret, str) else secret
    if len(raw) < MIN_SECRET_BYTES:
        return f"it is shorter than {MIN_SECRET_BYTES} bytes"
    if len(set(raw)) < _MIN_DISTINCT:
        return "it repeats a few characters instead of being random"
    lowered = raw.lower()
    for placeholder in _PLACEHOLDERS:
        if placeholder.encode() in lowered:
            return f"it contains the placeholder {placeholder!r}"
    return None
