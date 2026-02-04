from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from db.models.auth_external_identities import AuthExternalIdentityRow
from db.models.auth_mfa_factors import AuthMfaFactorRow
from db.models.auth_refresh_tokens import AuthRefreshTokenRow
from db.models.auth_users import AuthUserRow
from db.session import session_scope
from researchops_api.middlewares.auth import get_identity
from researchops_core.auth.config import get_auth_config
from researchops_core.auth.identity import Identity
from researchops_core.auth.google import verify_google_id_token
from researchops_core.auth.jwks_cache import JWKSCache
from researchops_core.auth.mfa import build_otpauth_uri, generate_totp_secret, verify_totp
from researchops_core.auth.passwords import hash_password, verify_password
from researchops_core.auth.tokens import (
    generate_refresh_token,
    hash_refresh_token,
    issue_access_token,
    issue_mfa_challenge_token,
    verify_mfa_challenge_token,
)
from researchops_core.settings import get_settings
from researchops_core.tenancy import tenant_uuid

router = APIRouter(tags=["auth"])


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=8, max_length=200)
    tenant_id: str | None = None


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=1, max_length=200)


class AuthTokensOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    access_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None
    user_id: str | None = None
    username: str | None = None
    tenant_id: str | None = None
    roles: list[str] = []
    mfa_required: bool = False
    mfa_token: str | None = None


class GoogleLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_token: str = Field(min_length=1, max_length=4096)
    tenant_id: str | None = None


class MfaEnrollStartOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: str
    otpauth_uri: str
    issuer: str
    account_name: str
    period: int
    digits: int


class MfaVerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=6, max_length=10)


class MfaChallengeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mfa_token: str = Field(min_length=10)
    code: str = Field(min_length=6, max_length=10)


class MfaStatusOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    pending: bool


@router.get("/me")
def me(identity: Identity = Depends(get_identity)) -> dict[str, object]:
    return {
        "user_id": identity.user_id,
        "username": identity.user_id,
        "tenant_id": identity.tenant_id,
        "roles": identity.roles,
    }


def _normalize_username(value: str) -> str:
    return value.strip().lower()


def _refresh_secret(cfg) -> str:
    return (cfg.auth_refresh_token_secret or cfg.auth_jwt_secret or "").strip()


def _refresh_cookie_settings() -> dict[str, object]:
    cfg = get_auth_config()
    settings = get_settings()
    secure = cfg.auth_refresh_cookie_secure
    if secure is None:
        secure = settings.environment != "local"
    return {
        "key": cfg.auth_refresh_cookie_name,
        "httponly": True,
        "secure": secure,
        "samesite": cfg.auth_refresh_cookie_samesite,
        "path": "/",
    }


def _set_refresh_cookie(response: Response, token: str, *, max_age_seconds: int) -> None:
    settings = _refresh_cookie_settings()
    response.set_cookie(
        settings["key"],
        token,
        max_age=max_age_seconds,
        httponly=settings["httponly"],
        secure=settings["secure"],
        samesite=settings["samesite"],
        path=settings["path"],
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = _refresh_cookie_settings()
    response.delete_cookie(settings["key"], path=settings["path"])


def _issue_tokens(user: AuthUserRow) -> tuple[str, str, datetime, int]:
    cfg = get_auth_config()
    if not cfg.auth_jwt_secret:
        raise HTTPException(status_code=500, detail="Auth secret not configured")
    access_token = issue_access_token(
        username=user.username,
        tenant_id=str(user.tenant_id),
        roles=user.roles_json or [],
        secret=cfg.auth_jwt_secret,
        issuer=cfg.auth_jwt_issuer,
        expires_minutes=cfg.auth_access_token_minutes,
    )
    refresh_token = generate_refresh_token()
    refresh_expires = datetime.now(timezone.utc) + timedelta(days=cfg.auth_refresh_token_days)
    return access_token, refresh_token, refresh_expires, cfg.auth_access_token_minutes * 60


def _persist_refresh_token(
    session,
    *,
    user: AuthUserRow,
    refresh_token: str,
    refresh_expires: datetime,
) -> None:
    cfg = get_auth_config()
    secret = _refresh_secret(cfg)
    if not secret:
        raise HTTPException(status_code=500, detail="Refresh token secret not configured")
    token_hash = hash_refresh_token(refresh_token, secret=secret)
    session.add(
        AuthRefreshTokenRow(
            tenant_id=user.tenant_id,
            user_id=user.id,
            token_hash=token_hash,
            expires_at=refresh_expires,
        )
    )


_GOOGLE_JWKS_CACHES: dict[str, JWKSCache] = {}


def _google_jwks_cache(cfg) -> JWKSCache:
    issuer = cfg.auth_google_issuer.rstrip("/")
    cache = _GOOGLE_JWKS_CACHES.get(issuer)
    if cache is None:
        cache = JWKSCache(issuer=issuer, cache_seconds=cfg.auth_google_jwks_cache_seconds)
        _GOOGLE_JWKS_CACHES[issuer] = cache
    return cache


def _mfa_factor(session, *, user_id) -> AuthMfaFactorRow | None:
    return (
        session.query(AuthMfaFactorRow)
        .filter(
            AuthMfaFactorRow.user_id == user_id,
            AuthMfaFactorRow.factor_type == "totp",
            AuthMfaFactorRow.enabled_at.isnot(None),
        )
        .one_or_none()
    )


def _issue_mfa_challenge(user: AuthUserRow) -> AuthTokensOut:
    cfg = get_auth_config()
    if not cfg.auth_jwt_secret:
        raise HTTPException(status_code=500, detail="Auth secret not configured")
    mfa_token = issue_mfa_challenge_token(
        user_id=str(user.id),
        tenant_id=str(user.tenant_id),
        secret=cfg.auth_jwt_secret,
        issuer=cfg.auth_jwt_issuer,
        expires_minutes=cfg.auth_mfa_challenge_minutes,
    )
    return AuthTokensOut(
        mfa_required=True,
        mfa_token=mfa_token,
        user_id=user.username,
        username=user.username,
        tenant_id=str(user.tenant_id),
        roles=user.roles_json or [],
    )


def _get_user_from_identity(session, identity: Identity) -> AuthUserRow | None:
    try:
        tenant = tenant_uuid(identity.tenant_id)
    except Exception:
        return None
    return (
        session.query(AuthUserRow)
        .filter(AuthUserRow.username == identity.user_id, AuthUserRow.tenant_id == tenant)
        .one_or_none()
    )


@router.post("/auth/register", response_model=AuthTokensOut)
def register(request: Request, response: Response, body: RegisterIn) -> AuthTokensOut:
    cfg = get_auth_config()
    if not cfg.auth_allow_register:
        raise HTTPException(status_code=403, detail="Registration disabled")

    username = _normalize_username(body.username)
    tenant_id = tenant_uuid(body.tenant_id) if body.tenant_id else uuid4()
    password_hash = hash_password(body.password)

    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        user = AuthUserRow(
            tenant_id=tenant_id,
            username=username,
            password_hash=password_hash,
            roles_json=["owner"],
            is_active=True,
        )
        session.add(user)
        try:
            session.flush()
        except IntegrityError as e:
            raise HTTPException(status_code=409, detail="Username already exists") from e

        access_token, refresh_token, refresh_expires, expires_in = _issue_tokens(user)
        _persist_refresh_token(
            session, user=user, refresh_token=refresh_token, refresh_expires=refresh_expires
        )
        _set_refresh_cookie(
            response,
            refresh_token,
            max_age_seconds=int((refresh_expires - datetime.now(timezone.utc)).total_seconds()),
        )

        return AuthTokensOut(
            access_token=access_token,
            expires_in=expires_in,
            user_id=user.username,
            username=user.username,
            tenant_id=str(user.tenant_id),
            roles=user.roles_json or [],
        )


@router.post("/auth/login", response_model=AuthTokensOut)
def login(request: Request, response: Response, body: LoginIn) -> AuthTokensOut:
    username = _normalize_username(body.username)
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        user = (
            session.query(AuthUserRow)
            .filter(AuthUserRow.username == username)
            .one_or_none()
        )
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        mfa_factor = _mfa_factor(session, user_id=user.id)
        if mfa_factor is not None:
            return _issue_mfa_challenge(user)

        access_token, refresh_token, refresh_expires, expires_in = _issue_tokens(user)
        _persist_refresh_token(
            session, user=user, refresh_token=refresh_token, refresh_expires=refresh_expires
        )
        _set_refresh_cookie(
            response,
            refresh_token,
            max_age_seconds=int((refresh_expires - datetime.now(timezone.utc)).total_seconds()),
        )

        return AuthTokensOut(
            access_token=access_token,
            expires_in=expires_in,
            user_id=user.username,
            username=user.username,
            tenant_id=str(user.tenant_id),
            roles=user.roles_json or [],
        )


@router.post("/auth/google", response_model=AuthTokensOut)
def google_login(request: Request, response: Response, body: GoogleLoginIn) -> AuthTokensOut:
    cfg = get_auth_config()
    if not cfg.auth_google_client_id:
        raise HTTPException(status_code=500, detail="Google login not configured")
    issuer = cfg.auth_google_issuer.rstrip("/")
    try:
        claims = verify_google_id_token(
            token=body.id_token,
            client_id=cfg.auth_google_client_id,
            issuer=issuer,
            clock_skew_seconds=cfg.auth_clock_skew_seconds,
            jwks_cache=_google_jwks_cache(cfg),
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid Google token") from e

    email = claims.get("email")
    email_verified = claims.get("email_verified")
    sub = claims.get("sub")
    if not isinstance(email, str) or not email.strip():
        raise HTTPException(status_code=400, detail="Google token missing email")
    if email_verified is False:
        raise HTTPException(status_code=401, detail="Google email not verified")
    if not isinstance(sub, str) or not sub.strip():
        raise HTTPException(status_code=401, detail="Google token missing subject")

    SessionLocal = request.app.state.SessionLocal
    now = datetime.now(timezone.utc)
    with session_scope(SessionLocal) as session:
        identity = (
            session.query(AuthExternalIdentityRow)
            .filter(
                AuthExternalIdentityRow.provider == "google",
                AuthExternalIdentityRow.provider_user_id == sub,
            )
            .one_or_none()
        )
        user = None
        if identity is not None:
            user = (
                session.query(AuthUserRow)
                .filter(AuthUserRow.id == identity.user_id)
                .one_or_none()
            )
            if user is None or not user.is_active:
                raise HTTPException(status_code=401, detail="Invalid account")
            identity.last_used_at = now
        else:
            username = _normalize_username(email)
            user = (
                session.query(AuthUserRow)
                .filter(AuthUserRow.username == username)
                .one_or_none()
            )
            if user is not None:
                if not cfg.auth_google_allow_link_existing:
                    raise HTTPException(status_code=409, detail="Account already exists")
                if not user.is_active:
                    raise HTTPException(status_code=401, detail="Invalid account")
                identity = AuthExternalIdentityRow(
                    tenant_id=user.tenant_id,
                    user_id=user.id,
                    provider="google",
                    provider_user_id=sub,
                    email=username,
                    last_used_at=now,
                )
                session.add(identity)
            else:
                if not cfg.auth_allow_register:
                    raise HTTPException(status_code=403, detail="Registration disabled")
                tenant_id = tenant_uuid(body.tenant_id) if body.tenant_id else uuid4()
                password_hash = hash_password(generate_refresh_token())
                user = AuthUserRow(
                    tenant_id=tenant_id,
                    username=username,
                    password_hash=password_hash,
                    roles_json=["owner"],
                    is_active=True,
                )
                session.add(user)
                session.flush()
                identity = AuthExternalIdentityRow(
                    tenant_id=user.tenant_id,
                    user_id=user.id,
                    provider="google",
                    provider_user_id=sub,
                    email=username,
                    last_used_at=now,
                )
                session.add(identity)

        if user is None:
            raise HTTPException(status_code=401, detail="Invalid account")

        mfa_factor = _mfa_factor(session, user_id=user.id)
        if mfa_factor is not None:
            return _issue_mfa_challenge(user)

        access_token, refresh_token, refresh_expires, expires_in = _issue_tokens(user)
        _persist_refresh_token(
            session, user=user, refresh_token=refresh_token, refresh_expires=refresh_expires
        )
        _set_refresh_cookie(
            response,
            refresh_token,
            max_age_seconds=int((refresh_expires - now).total_seconds()),
        )

        return AuthTokensOut(
            access_token=access_token,
            expires_in=expires_in,
            user_id=user.username,
            username=user.username,
            tenant_id=str(user.tenant_id),
            roles=user.roles_json or [],
        )


@router.post("/auth/refresh", response_model=AuthTokensOut)
def refresh(request: Request, response: Response) -> AuthTokensOut:
    cfg = get_auth_config()
    secret = _refresh_secret(cfg)
    if not secret:
        raise HTTPException(status_code=500, detail="Refresh token secret not configured")
    raw = request.cookies.get(cfg.auth_refresh_cookie_name)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing refresh token")
    token_hash = hash_refresh_token(raw, secret=secret)
    now = datetime.now(timezone.utc)

    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        token_row = (
            session.query(AuthRefreshTokenRow)
            .filter(AuthRefreshTokenRow.token_hash == token_hash)
            .one_or_none()
        )
        if token_row is None or token_row.revoked_at is not None:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        if token_row.expires_at <= now:
            raise HTTPException(status_code=401, detail="Refresh token expired")

        user = session.query(AuthUserRow).filter(AuthUserRow.id == token_row.user_id).one_or_none()
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        token_row.revoked_at = now
        token_row.last_used_at = now

        access_token, refresh_token, refresh_expires, expires_in = _issue_tokens(user)
        _persist_refresh_token(
            session, user=user, refresh_token=refresh_token, refresh_expires=refresh_expires
        )
        _set_refresh_cookie(
            response,
            refresh_token,
            max_age_seconds=int((refresh_expires - now).total_seconds()),
        )

        return AuthTokensOut(
            access_token=access_token,
            expires_in=expires_in,
            user_id=user.username,
            username=user.username,
            tenant_id=str(user.tenant_id),
            roles=user.roles_json or [],
        )


@router.get("/auth/mfa/status", response_model=MfaStatusOut)
def mfa_status(request: Request, identity: Identity = Depends(get_identity)) -> MfaStatusOut:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        user = _get_user_from_identity(session, identity)
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid account")
        factor = (
            session.query(AuthMfaFactorRow)
            .filter(
                AuthMfaFactorRow.user_id == user.id,
                AuthMfaFactorRow.factor_type == "totp",
            )
            .one_or_none()
        )
        enabled = bool(factor and factor.enabled_at)
        pending = bool(factor and not factor.enabled_at)
        return MfaStatusOut(enabled=enabled, pending=pending)


@router.post("/auth/mfa/enroll/start", response_model=MfaEnrollStartOut)
def mfa_enroll_start(
    request: Request, identity: Identity = Depends(get_identity)
) -> MfaEnrollStartOut:
    cfg = get_auth_config()
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        user = _get_user_from_identity(session, identity)
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid account")
        factor = (
            session.query(AuthMfaFactorRow)
            .filter(
                AuthMfaFactorRow.user_id == user.id,
                AuthMfaFactorRow.factor_type == "totp",
            )
            .one_or_none()
        )
        if factor is not None and factor.enabled_at is not None:
            raise HTTPException(status_code=409, detail="MFA already enabled")

        secret = generate_totp_secret()
        if factor is None:
            factor = AuthMfaFactorRow(
                tenant_id=user.tenant_id,
                user_id=user.id,
                factor_type="totp",
                secret=secret,
            )
            session.add(factor)
        else:
            factor.secret = secret
            factor.enabled_at = None
            factor.last_used_at = None

        otpauth_uri = build_otpauth_uri(
            secret=secret,
            account_name=user.username,
            issuer=cfg.auth_mfa_totp_issuer,
            period=cfg.auth_mfa_totp_period_seconds,
            digits=cfg.auth_mfa_totp_digits,
        )
        return MfaEnrollStartOut(
            secret=secret,
            otpauth_uri=otpauth_uri,
            issuer=cfg.auth_mfa_totp_issuer,
            account_name=user.username,
            period=cfg.auth_mfa_totp_period_seconds,
            digits=cfg.auth_mfa_totp_digits,
        )


@router.post("/auth/mfa/enroll/verify")
def mfa_enroll_verify(
    request: Request, body: MfaVerifyIn, identity: Identity = Depends(get_identity)
) -> dict[str, object]:
    cfg = get_auth_config()
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        user = _get_user_from_identity(session, identity)
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid account")
        factor = (
            session.query(AuthMfaFactorRow)
            .filter(
                AuthMfaFactorRow.user_id == user.id,
                AuthMfaFactorRow.factor_type == "totp",
            )
            .one_or_none()
        )
        if factor is None:
            raise HTTPException(status_code=404, detail="MFA enrollment not found")
        if factor.enabled_at is not None:
            return {"enabled": True}
        if not verify_totp(
            code=body.code,
            secret=factor.secret,
            period=cfg.auth_mfa_totp_period_seconds,
            digits=cfg.auth_mfa_totp_digits,
            window=cfg.auth_mfa_totp_window,
        ):
            raise HTTPException(status_code=401, detail="Invalid MFA code")
        now = datetime.now(timezone.utc)
        factor.enabled_at = now
        factor.last_used_at = now
        return {"enabled": True}


@router.post("/auth/mfa/disable")
def mfa_disable(
    request: Request, body: MfaVerifyIn, identity: Identity = Depends(get_identity)
) -> dict[str, object]:
    cfg = get_auth_config()
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        user = _get_user_from_identity(session, identity)
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid account")
        factor = (
            session.query(AuthMfaFactorRow)
            .filter(
                AuthMfaFactorRow.user_id == user.id,
                AuthMfaFactorRow.factor_type == "totp",
            )
            .one_or_none()
        )
        if factor is None or factor.enabled_at is None:
            return {"enabled": False}
        if not verify_totp(
            code=body.code,
            secret=factor.secret,
            period=cfg.auth_mfa_totp_period_seconds,
            digits=cfg.auth_mfa_totp_digits,
            window=cfg.auth_mfa_totp_window,
        ):
            raise HTTPException(status_code=401, detail="Invalid MFA code")
        session.delete(factor)
        return {"enabled": False}


@router.post("/auth/mfa/verify", response_model=AuthTokensOut)
def mfa_verify(request: Request, response: Response, body: MfaChallengeIn) -> AuthTokensOut:
    cfg = get_auth_config()
    if not cfg.auth_jwt_secret:
        raise HTTPException(status_code=500, detail="Auth secret not configured")
    try:
        claims = verify_mfa_challenge_token(
            token=body.mfa_token,
            secret=cfg.auth_jwt_secret,
            issuer=cfg.auth_jwt_issuer,
            clock_skew_seconds=cfg.auth_clock_skew_seconds,
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid MFA token") from e

    user_id = claims.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="Invalid MFA token")
    try:
        user_uuid = UUID(user_id)
    except ValueError as e:
        raise HTTPException(status_code=401, detail="Invalid MFA token") from e

    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        user = session.query(AuthUserRow).filter(AuthUserRow.id == user_uuid).one_or_none()
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid MFA token")
        tenant_claim = claims.get("tenant_id")
        if isinstance(tenant_claim, str) and tenant_claim != str(user.tenant_id):
            raise HTTPException(status_code=401, detail="Invalid MFA token")
        factor = _mfa_factor(session, user_id=user.id)
        if factor is None:
            raise HTTPException(status_code=401, detail="MFA not enabled")
        if not verify_totp(
            code=body.code,
            secret=factor.secret,
            period=cfg.auth_mfa_totp_period_seconds,
            digits=cfg.auth_mfa_totp_digits,
            window=cfg.auth_mfa_totp_window,
        ):
            raise HTTPException(status_code=401, detail="Invalid MFA code")

        now = datetime.now(timezone.utc)
        factor.last_used_at = now

        access_token, refresh_token, refresh_expires, expires_in = _issue_tokens(user)
        _persist_refresh_token(
            session, user=user, refresh_token=refresh_token, refresh_expires=refresh_expires
        )
        _set_refresh_cookie(
            response,
            refresh_token,
            max_age_seconds=int((refresh_expires - now).total_seconds()),
        )

        return AuthTokensOut(
            access_token=access_token,
            expires_in=expires_in,
            user_id=user.username,
            username=user.username,
            tenant_id=str(user.tenant_id),
            roles=user.roles_json or [],
        )


@router.post("/auth/logout")
def logout(request: Request, response: Response) -> dict[str, str]:
    cfg = get_auth_config()
    secret = _refresh_secret(cfg)
    raw = request.cookies.get(cfg.auth_refresh_cookie_name)
    if raw and secret:
        token_hash = hash_refresh_token(raw, secret=secret)
        SessionLocal = request.app.state.SessionLocal
        with session_scope(SessionLocal) as session:
            token_row = (
                session.query(AuthRefreshTokenRow)
                .filter(AuthRefreshTokenRow.token_hash == token_hash)
                .one_or_none()
            )
            if token_row is not None and token_row.revoked_at is None:
                token_row.revoked_at = datetime.now(timezone.utc)
    _clear_refresh_cookie(response)
    return {"status": "ok"}
