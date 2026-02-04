from __future__ import annotations

import json
from typing import Any

import jwt

from researchops_core.auth.exceptions import AuthInvalidTokenError
from researchops_core.auth.jwks_cache import JWKSCache


def verify_google_id_token(
    *,
    token: str,
    client_id: str,
    issuer: str,
    clock_skew_seconds: int = 60,
    jwks_cache: JWKSCache | None = None,
) -> dict[str, Any]:
    if not token:
        raise AuthInvalidTokenError("Empty Google ID token")
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise AuthInvalidTokenError("Invalid Google ID token header") from e

    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise AuthInvalidTokenError("Missing Google ID token kid")

    cache = jwks_cache or JWKSCache(issuer=issuer)
    jwks = cache.get_jwks()
    keys = jwks.get("keys", [])
    key = next((k for k in keys if k.get("kid") == kid), None)
    if key is None:
        raise AuthInvalidTokenError("Google ID token key not found")

    public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
    try:
        claims = jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=[issuer, "accounts.google.com"],
            leeway=clock_skew_seconds,
            options={"require": ["exp", "sub", "iat"], "verify_signature": True},
        )
    except jwt.PyJWTError as e:
        raise AuthInvalidTokenError("Invalid Google ID token") from e

    if not isinstance(claims, dict):
        raise AuthInvalidTokenError("Invalid Google ID token claims")
    return claims
