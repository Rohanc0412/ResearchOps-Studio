from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from researchops_core.auth.exceptions import AuthExpiredError, AuthInvalidTokenError, AuthIssuerError
from researchops_core.auth.tokens import issue_access_token, verify_access_token


def test_access_token_round_trip() -> None:
    secret = "secret"
    token = issue_access_token(
        username="alice",
        tenant_id="tenant-1",
        roles=["viewer"],
        secret=secret,
        issuer="issuer",
        expires_minutes=5,
    )
    claims = verify_access_token(
        token=token, secret=secret, issuer="issuer", clock_skew_seconds=0
    )
    assert claims["sub"] == "alice"
    assert claims["tenant_id"] == "tenant-1"
    assert "roles" in claims


def test_access_token_wrong_secret() -> None:
    token = issue_access_token(
        username="alice",
        tenant_id="tenant-1",
        roles=["viewer"],
        secret="secret",
        issuer="issuer",
        expires_minutes=5,
    )
    with pytest.raises(AuthInvalidTokenError):
        verify_access_token(token=token, secret="wrong", issuer="issuer", clock_skew_seconds=0)


def test_access_token_wrong_issuer() -> None:
    token = issue_access_token(
        username="alice",
        tenant_id="tenant-1",
        roles=["viewer"],
        secret="secret",
        issuer="issuer",
        expires_minutes=5,
    )
    with pytest.raises(AuthIssuerError):
        verify_access_token(token=token, secret="secret", issuer="other", clock_skew_seconds=0)


def test_access_token_expired() -> None:
    now = datetime.now(timezone.utc)
    expired = now - timedelta(minutes=5)
    payload = {
        "sub": "alice",
        "iss": "issuer",
        "iat": int(expired.timestamp()),
        "exp": int((expired + timedelta(minutes=1)).timestamp()),
    }
    token = jwt.encode(payload, "secret", algorithm="HS256")
    with pytest.raises(AuthExpiredError):
        verify_access_token(token=token, secret="secret", issuer="issuer", clock_skew_seconds=0)
