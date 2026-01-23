from __future__ import annotations

from typing import Any

import jwt
from jwt import InvalidAudienceError, InvalidIssuerError
from jwt.exceptions import ExpiredSignatureError, InvalidAlgorithmError, InvalidSignatureError, PyJWTError
from jwt.algorithms import RSAAlgorithm

from researchops_core.auth.exceptions import (
    AuthAudienceError,
    AuthExpiredError,
    AuthInvalidTokenError,
    AuthIssuerError,
)
from researchops_core.auth.jwks_cache import JWKSCache


def verify_jwt(
    *,
    token: str,
    issuer: str,
    audience: str,
    jwks_cache: JWKSCache,
    clock_skew_seconds: int = 60,
) -> dict[str, Any]:
    if not token or not isinstance(token, str):
        raise AuthInvalidTokenError("Empty token")

    header = jwt.get_unverified_header(token)
    alg = header.get("alg")
    if alg is None or alg == "none":
        raise AuthInvalidTokenError("Rejected JWT with alg=none")

    kid = header.get("kid")
    jwks = jwks_cache.get_jwks()
    keys = jwks.get("keys", [])
    if not isinstance(keys, list):
        raise AuthInvalidTokenError("Invalid JWKS keys")

    key: dict[str, Any] | None = None
    if kid:
        for k in keys:
            if isinstance(k, dict) and k.get("kid") == kid:
                key = k
                break
    if key is None:
        # Fallback: try first key (useful for single-key test rigs)
        if keys and isinstance(keys[0], dict):
            key = keys[0]
    if key is None:
        raise AuthInvalidTokenError("No JWKS key available for token")

    try:
        public_key = _public_key_from_jwk(key)
        claims = jwt.decode(
            token,
            key=public_key,
            algorithms=[alg],
            issuer=issuer.rstrip("/"),
            audience=audience,
            options={"require": ["exp", "sub", "iat"], "verify_signature": True},
            leeway=clock_skew_seconds,
        )
    except ExpiredSignatureError as e:
        raise AuthExpiredError("JWT expired") from e
    except InvalidIssuerError as e:
        raise AuthIssuerError("JWT issuer mismatch") from e
    except InvalidAudienceError as e:
        raise AuthAudienceError("JWT audience mismatch") from e
    except (InvalidSignatureError, InvalidAlgorithmError, PyJWTError) as e:
        raise AuthInvalidTokenError("Invalid JWT") from e

    if not isinstance(claims, dict):
        raise AuthInvalidTokenError("Invalid JWT claims payload")
    if not isinstance(claims.get("sub"), str) or not claims["sub"].strip():
        raise AuthInvalidTokenError("JWT missing required 'sub'")
    return claims


def _public_key_from_jwk(jwk: dict[str, Any]):
    kty = jwk.get("kty")
    if kty != "RSA":
        raise AuthInvalidTokenError(f"Unsupported JWK kty: {kty}")
    import json

    return RSAAlgorithm.from_jwk(json.dumps(jwk))
