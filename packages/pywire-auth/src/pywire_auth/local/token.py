"""JWT issuance + verification for the local IdP.

Wraps ``authlib.jose`` with two preset modes:

- ``HS256`` — symmetric, single secret. Default for simple deployments.
- ``RS256`` — asymmetric; provides a PEM public key for cross-service
  verification.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from authlib.jose import JsonWebKey, JsonWebToken

from pywire.runtime.secret_key import GENERATE_HINT, weak_secret

# Claims the issuer owns. Caller-supplied claims never replace them: a
# token's issuer, audience, subject and lifetime are what verifiers trust.
RESERVED_CLAIMS = frozenset({"iss", "sub", "aud", "iat", "exp", "nbf", "jti"})


@dataclass
class TokenIssuer:
    """Minimal id_token issuer.

    ``secret`` is used for HS256. For RS256 pass ``private_key_pem`` and
    optionally ``public_key_pem`` (derived from the private key when
    omitted).
    """

    issuer: str = "pywire-auth-local"
    algorithm: str = "HS256"
    secret: str = ""
    private_key_pem: str = ""
    public_key_pem: str = ""
    default_ttl: int = 3600
    kid: str = "local"
    _public_jwk: Optional[Dict[str, Any]] = field(default=None, init=False, repr=False)
    # Accepts only this issuer's algorithm, so a token can't pick another
    # (e.g. HS256 keyed with the RS256 public key).
    _jwt: JsonWebToken = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.algorithm == "HS256":
            if not self.secret:
                raise ValueError("HS256 issuer requires a non-empty secret")
            # Anyone holding one token can test guesses offline.
            weakness = weak_secret(self.secret)
            if weakness is not None:
                raise ValueError(
                    "HS256 issuer secret must be at least 32 random bytes, and "
                    f"this one isn't: {weakness}. {GENERATE_HINT}"
                )
        elif self.algorithm == "RS256":
            if not self.private_key_pem:
                raise ValueError("RS256 issuer requires private_key_pem")
        else:
            raise ValueError(
                f"Unsupported algorithm {self.algorithm!r} — use HS256 or RS256"
            )
        self._jwt = JsonWebToken([self.algorithm])

    def issue(
        self,
        *,
        subject: str,
        audience: str,
        claims: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None,
    ) -> str:
        """Sign a token for ``subject``.

        ``claims`` add to the token; the registered claims (``iss``, ``sub``,
        ``aud``, ``iat``, ``exp``, ``nbf``, ``jti``) always come from the
        issuer and the arguments here, never from ``claims``.
        """
        now = int(time.time())
        payload: Dict[str, Any] = {
            k: v for k, v in (claims or {}).items() if k not in RESERVED_CLAIMS
        }
        payload.update(
            iss=self.issuer,
            sub=subject,
            aud=audience,
            iat=now,
            exp=now + (ttl or self.default_ttl),
        )
        header = {"alg": self.algorithm, "kid": self.kid}
        key = self.secret if self.algorithm == "HS256" else self.private_key_pem
        token = self._jwt.encode(header, payload, key)
        return token.decode("utf-8") if isinstance(token, bytes) else token

    def verify(
        self, token: str, *, audience: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Return the decoded claims dict if valid; None otherwise.

        Valid means signed by this issuer, issued by it (``iss``), not
        expired (``exp`` is required) and, when ``audience`` is given, for
        that audience.
        """
        key = (
            self.secret
            if self.algorithm == "HS256"
            else (self.public_key_pem or self.private_key_pem)
        )
        options: Dict[str, Any] = {
            "iss": {"essential": True, "value": self.issuer},
            "exp": {"essential": True},
        }
        if audience is not None:
            options["aud"] = {"essential": True, "value": audience}
        try:
            claims = self._jwt.decode(token, key, claims_options=options)
            claims.validate()
        except Exception:
            return None
        return dict(claims)

    def public_jwks(self) -> Dict[str, Any]:
        """Return the JWKS for this issuer (RS256 only).

        HS256 has no public key — raises ``RuntimeError`` to prevent
        accidentally publishing the shared secret.
        """
        if self.algorithm != "RS256":
            raise RuntimeError("public_jwks() is only meaningful for RS256")
        if self._public_jwk is None:
            pem = self.public_key_pem or self.private_key_pem
            jwk = JsonWebKey.import_key(pem, {"kty": "RSA", "use": "sig"})
            data = jwk.as_dict()
            data["alg"] = self.algorithm
            data["kid"] = self.kid
            self._public_jwk = data
        return {"keys": [self._public_jwk]}
