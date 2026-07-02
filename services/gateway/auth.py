"""Task 74 — JWT verification (OIDC-compatible).

`verify_token` validates signature, expiry, audience, and issuer using the
configured algorithm(s):
  * HS256 — symmetric secret (default; dev / service-to-service / tests),
  * RS256 — OIDC provider keys fetched from `jwks_url` (production SSO).
`mint_token` issues HS256 tokens for local dev and the test-suite. Numbers and
clearance are never inferred here — clearance is read from a signed claim only.
All failures raise `AuthError` with a stable, log-safe reason.
"""
from __future__ import annotations
import time

import jwt   # PyJWT
from jwt import PyJWKClient


class AuthError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def mint_token(sub: str, clearance: str = "OPEN", *, scopes: list[str] | None = None,
               persona: str = "analyst", ttl: int = 3600, secret: str,
               issuer: str | None = None, audience: str | None = None,
               algorithm: str = "HS256", clearance_claim: str = "clearance",
               extra: dict | None = None) -> str:
    """Dev/test token minting (HS256). Production tokens come from the OIDC IdP."""
    now = int(time.time())
    payload = {"sub": sub, clearance_claim: clearance, "persona": persona,
               "iat": now, "nbf": now, "exp": now + ttl}
    if scopes:
        payload["scope"] = " ".join(scopes)
    if issuer:
        payload["iss"] = issuer
    if audience:
        payload["aud"] = audience
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret, algorithm=algorithm)


def _key_for(token: str, settings):
    """Resolve the verification key: JWKS signing key for RS-family, else the secret."""
    algs = settings.jwt_algorithm_list
    if any(a.startswith("RS") or a.startswith("ES") or a.startswith("PS") for a in algs):
        if not settings.jwks_url:
            raise AuthError("asymmetric algorithm configured but jwks_url unset")
        try:
            return PyJWKClient(settings.jwks_url).get_signing_key_from_jwt(token).key
        except Exception as ex:                       # network / key resolution
            raise AuthError(f"jwks key resolution failed: {type(ex).__name__}")
    return settings.jwt_secret


def verify_token(token: str, settings) -> dict:
    """Verify and decode a bearer token → claims dict, or raise AuthError."""
    if not token:
        raise AuthError("missing token")
    options = {"require": ["exp"], "verify_aud": settings.jwt_audience is not None}
    try:
        return jwt.decode(
            token, _key_for(token, settings),
            algorithms=settings.jwt_algorithm_list,
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options=options,
        )
    except jwt.ExpiredSignatureError:
        raise AuthError("token expired")
    except jwt.InvalidAudienceError:
        raise AuthError("invalid audience")
    except jwt.InvalidIssuerError:
        raise AuthError("invalid issuer")
    except jwt.InvalidSignatureError:
        raise AuthError("invalid signature")
    except AuthError:
        raise
    except jwt.PyJWTError as ex:
        raise AuthError(f"invalid token: {type(ex).__name__}")
