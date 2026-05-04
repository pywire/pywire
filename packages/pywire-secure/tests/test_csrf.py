"""Tests for stateless HMAC CSRF tokens."""

from __future__ import annotations

import pytest

from pywire_secure.csrf import (
    DOMAIN,
    _parse_token,
    _sign,
    generate_token,
    verify_token,
)

SECRET = "test-secret-32-bytes-padded-xxxxxx"
SESSION = "abc123sessionid"


def test_generate_token_format() -> None:
    token = generate_token(SESSION, SECRET)
    assert ":" in token
    ts, sig = token.split(":", 1)
    assert ts.isdigit()
    assert len(sig) == 32
    assert all(c in "0123456789abcdef" for c in sig)


def test_round_trip() -> None:
    token = generate_token(SESSION, SECRET)
    assert verify_token(token, SESSION, SECRET) is True


def test_wrong_session_rejected() -> None:
    token = generate_token(SESSION, SECRET)
    assert verify_token(token, "different-session", SECRET) is False


def test_wrong_secret_rejected() -> None:
    token = generate_token(SESSION, SECRET)
    assert verify_token(token, SESSION, "different-secret") is False


def test_tampered_signature_rejected() -> None:
    token = generate_token(SESSION, SECRET)
    ts, sig = token.split(":", 1)
    flipped = sig[:-1] + ("0" if sig[-1] != "0" else "1")
    tampered = f"{ts}:{flipped}"
    assert verify_token(tampered, SESSION, SECRET) is False


def test_tampered_timestamp_rejected() -> None:
    token = generate_token(SESSION, SECRET, now=1_000_000)
    _, sig = token.split(":", 1)
    tampered = f"999999:{sig}"
    assert verify_token(tampered, SESSION, SECRET) is False


def test_expired_token_rejected() -> None:
    token = generate_token(SESSION, SECRET, ttl=60, now=1_000_000)
    assert verify_token(token, SESSION, SECRET, ttl=60, now=1_000_120) is False


def test_token_within_ttl_accepted() -> None:
    token = generate_token(SESSION, SECRET, ttl=60, now=1_000_000)
    assert verify_token(token, SESSION, SECRET, ttl=60, now=1_000_059) is True


def test_zero_ttl_disables_expiry() -> None:
    token = generate_token(SESSION, SECRET, ttl=0)
    ts, _ = token.split(":", 1)
    assert ts == "0"
    assert verify_token(token, SESSION, SECRET, ttl=0, now=10**12) is True


def test_empty_token_rejected() -> None:
    assert verify_token("", SESSION, SECRET) is False


def test_empty_session_rejected_on_generate() -> None:
    assert generate_token("", SECRET) == ""


def test_empty_session_rejected_on_verify() -> None:
    token = generate_token(SESSION, SECRET)
    assert verify_token(token, "", SECRET) is False


def test_malformed_token_no_separator() -> None:
    assert verify_token("notatoken", SESSION, SECRET) is False


def test_malformed_token_short_signature() -> None:
    assert verify_token("123:short", SESSION, SECRET) is False


def test_malformed_token_empty_timestamp() -> None:
    assert verify_token(":" + "a" * 32, SESSION, SECRET) is False


def test_malformed_timestamp_non_numeric() -> None:
    sig = _sign(SESSION, "abc", SECRET)
    assert verify_token(f"abc:{sig}", SESSION, SECRET) is False


def test_domain_separation_session_signing() -> None:
    """Token signature must differ from a same-shape signature without the
    CSRF domain prefix — guarantees a session-cookie HMAC under the same
    secret cannot be replayed as a CSRF token."""
    import hashlib
    import hmac

    token = generate_token(SESSION, SECRET, now=1_000_000)
    _, csrf_sig = token.split(":", 1)
    naive_sig = hmac.new(
        SECRET.encode(),
        f"{SESSION}:1000000".encode(),
        hashlib.sha256,
    ).hexdigest()[:32]
    assert csrf_sig != naive_sig


def test_parse_token_roundtrip() -> None:
    token = generate_token(SESSION, SECRET, now=42)
    parsed = _parse_token(token)
    assert parsed is not None
    ts, sig = parsed
    assert ts == "42"
    assert len(sig) == 32


@pytest.mark.parametrize("token", ["", "x", ":", "1:", ":sig", "1:short"])
def test_parse_token_rejects_garbage(token: str) -> None:
    assert _parse_token(token) is None or len(_parse_token(token)[1]) == 32  # type: ignore[index]


def test_domain_constant_stable() -> None:
    """Pinning the domain string prevents accidental changes that would
    silently invalidate every issued token at the next deploy."""
    assert DOMAIN == "pywire-csrf-v1"
