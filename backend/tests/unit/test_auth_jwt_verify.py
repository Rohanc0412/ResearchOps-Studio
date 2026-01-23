from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from researchops_core.auth.exceptions import (
    AuthAudienceError,
    AuthExpiredError,
    AuthInvalidTokenError,
    AuthIssuerError,
)
from researchops_core.auth.jwks_cache import JWKSCache
from researchops_core.auth.jwt_verify import verify_jwt


def _rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


def _jwk_from_public(public_key, *, kid: str) -> dict:
    from jwt.algorithms import RSAAlgorithm

    jwk = RSAAlgorithm.to_jwk(public_key)
    d = json.loads(jwk)
    d["kid"] = kid
    d["use"] = "sig"
    d["alg"] = "RS256"
    return d


def _mint(*, private_key, issuer: str, audience: str, kid: str, exp_seconds: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "user_1",
        "iss": issuer.rstrip("/"),
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=exp_seconds)).timestamp()),
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})


def _jwks_cache_for(*, issuer: str, jwks: dict) -> JWKSCache:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={"jwks_uri": f"{issuer.rstrip('/')}/jwks"})
        if request.url.path == "/jwks":
            return httpx.Response(200, json=jwks)
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url=issuer.rstrip("/"))
    return JWKSCache(issuer=issuer, cache_seconds=300, http_client=client)


def test_jwt_rejects_invalid_signature() -> None:
    issuer = "http://issuer.test"
    audience = "aud"
    kid = "kid1"
    priv_good, pub_good = _rsa_keypair()
    priv_bad, _ = _rsa_keypair()

    jwks = {"keys": [_jwk_from_public(pub_good, kid=kid)]}
    cache = _jwks_cache_for(issuer=issuer, jwks=jwks)
    token = _mint(private_key=priv_bad, issuer=issuer, audience=audience, kid=kid, exp_seconds=60)

    with pytest.raises(AuthInvalidTokenError):
        verify_jwt(token=token, issuer=issuer, audience=audience, jwks_cache=cache, clock_skew_seconds=0)


def test_jwt_rejects_wrong_issuer() -> None:
    issuer = "http://issuer.test"
    audience = "aud"
    kid = "kid1"
    priv, pub = _rsa_keypair()
    jwks = {"keys": [_jwk_from_public(pub, kid=kid)]}
    cache = _jwks_cache_for(issuer=issuer, jwks=jwks)
    token = _mint(private_key=priv, issuer="http://wrong-issuer", audience=audience, kid=kid, exp_seconds=60)

    with pytest.raises(AuthIssuerError):
        verify_jwt(token=token, issuer=issuer, audience=audience, jwks_cache=cache, clock_skew_seconds=0)


def test_jwt_rejects_wrong_audience() -> None:
    issuer = "http://issuer.test"
    audience = "aud"
    kid = "kid1"
    priv, pub = _rsa_keypair()
    jwks = {"keys": [_jwk_from_public(pub, kid=kid)]}
    cache = _jwks_cache_for(issuer=issuer, jwks=jwks)
    token = _mint(private_key=priv, issuer=issuer, audience="wrong", kid=kid, exp_seconds=60)

    with pytest.raises(AuthAudienceError):
        verify_jwt(token=token, issuer=issuer, audience=audience, jwks_cache=cache, clock_skew_seconds=0)


def test_jwt_rejects_expired() -> None:
    issuer = "http://issuer.test"
    audience = "aud"
    kid = "kid1"
    priv, pub = _rsa_keypair()
    jwks = {"keys": [_jwk_from_public(pub, kid=kid)]}
    cache = _jwks_cache_for(issuer=issuer, jwks=jwks)
    token = _mint(private_key=priv, issuer=issuer, audience=audience, kid=kid, exp_seconds=-1)

    with pytest.raises(AuthExpiredError):
        verify_jwt(token=token, issuer=issuer, audience=audience, jwks_cache=cache, clock_skew_seconds=0)

