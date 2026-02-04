from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt import InvalidIssuerError
from jwt.exceptions import ExpiredSignatureError, PyJWTError

from researchops_core.auth.exceptions import AuthExpiredError, AuthInvalidTokenError, AuthIssuerError
from researchops_core.auth.identity import TENANT_CLAIM_PRIMARY


def issue_access_token(
    *,
    username: str,
    tenant_id: str,
    roles: list[str],
    secret: str,
    issuer: str,
    expires_minutes: int,
    now: datetime | None = None,
) -> str:
    if not username or not tenant_id:
        raise ValueError("username and tenant_id are required")
    now_dt = now or datetime.now(timezone.utc)
    exp = now_dt + timedelta(minutes=expires_minutes)
    payload: dict[str, Any] = {
        "sub": username,
        "iss": issuer,
        "iat": int(now_dt.timestamp()),
        "exp": int(exp.timestamp()),
        TENANT_CLAIM_PRIMARY: tenant_id,
        "tenant_id": tenant_id,
        "roles": roles,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def issue_mfa_challenge_token(
    *,
    user_id: str,
    tenant_id: str,
    secret: str,
    issuer: str,
    expires_minutes: int,
    now: datetime | None = None,
) -> str:
    if not user_id or not tenant_id:
        raise ValueError("user_id and tenant_id are required")
    now_dt = now or datetime.now(timezone.utc)
    exp = now_dt + timedelta(minutes=expires_minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "iss": issuer,
        "iat": int(now_dt.timestamp()),
        "exp": int(exp.timestamp()),
        "tenant_id": tenant_id,
        "purpose": "mfa",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_mfa_challenge_token(
    *,
    token: str,
    secret: str,
    issuer: str,
    clock_skew_seconds: int = 60,
) -> dict[str, Any]:
    if not token or not isinstance(token, str):
        raise AuthInvalidTokenError("Empty MFA token")
    try:
        claims = jwt.decode(
            token,
            key=secret,
            algorithms=["HS256"],
            issuer=issuer,
            options={"require": ["exp", "sub", "iat"], "verify_signature": True},
            leeway=clock_skew_seconds,
        )
    except ExpiredSignatureError as e:
        raise AuthExpiredError("MFA token expired") from e
    except InvalidIssuerError as e:
        raise AuthIssuerError("MFA token issuer mismatch") from e
    except PyJWTError as e:
        raise AuthInvalidTokenError("Invalid MFA token") from e
    if not isinstance(claims, dict):
        raise AuthInvalidTokenError("Invalid MFA token claims payload")
    if claims.get("purpose") != "mfa":
        raise AuthInvalidTokenError("Invalid MFA token purpose")
    return claims


def verify_access_token(
    *,
    token: str,
    secret: str,
    issuer: str,
    clock_skew_seconds: int = 60,
) -> dict[str, Any]:
    if not token or not isinstance(token, str):
        raise AuthInvalidTokenError("Empty token")
    try:
        claims = jwt.decode(
            token,
            key=secret,
            algorithms=["HS256"],
            issuer=issuer,
            options={"require": ["exp", "sub", "iat"], "verify_signature": True},
            leeway=clock_skew_seconds,
        )
    except ExpiredSignatureError as e:
        raise AuthExpiredError("JWT expired") from e
    except InvalidIssuerError as e:
        raise AuthIssuerError("JWT issuer mismatch") from e
    except PyJWTError as e:
        raise AuthInvalidTokenError("Invalid JWT") from e
    if not isinstance(claims, dict):
        raise AuthInvalidTokenError("Invalid JWT claims payload")
    if not isinstance(claims.get("sub"), str) or not claims["sub"].strip():
        raise AuthInvalidTokenError("JWT missing required 'sub'")
    return claims


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str, *, secret: str) -> str:
    if not token:
        raise ValueError("Refresh token required")
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()
