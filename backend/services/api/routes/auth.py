from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from core.auth.config import get_auth_config
from core.auth.identity import Identity
from core.auth.mfa import build_otpauth_uri, generate_totp_secret, verify_totp
from core.auth.passwords import hash_password, verify_password
from core.auth.tokens import (
    generate_refresh_token,
    hash_password_reset_token,
    hash_refresh_token,
    issue_access_token,
    issue_mfa_challenge_token,
    verify_mfa_challenge_token,
)
from core.settings import get_settings
from core.tenancy import tenant_uuid
from db.models.auth_mfa_factors import AuthMfaFactorRow
from db.models.auth_users import AuthUserRow
from db.repositories.identity import (
    create_password_reset,
    create_refresh_token,
    create_user,
    delete_mfa_factor,
    get_mfa_factor,
    get_password_reset_by_hash,
    get_refresh_token_by_hash,
    get_user_by_email,
    get_user_by_id,
    get_user_by_identity,
    get_user_by_username_or_email,
    list_role_names,
    revoke_refresh_token,
    revoke_refresh_tokens_for_user,
    upsert_mfa_factor,
)
from deps import DBDep
from fastapi import APIRouter, HTTPException, Request, Response
from middlewares.auth import IdentityDep
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from utils.email import send_password_reset_otp

router = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)


def _email_domain(value: str) -> str | None:
    value = (value or "").strip().lower()
    if "@" not in value:
        return None
    domain = value.split("@", 1)[1].strip()
    return domain or None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=120)
    email: str | None = Field(default=None, min_length=3, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    tenant_id: str | None = None


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=200)
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


class PasswordResetRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=200)


class PasswordResetConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=6, max_length=10)
    password: str = Field(min_length=8, max_length=200)


class PasswordResetRequestOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = "ok"
    reset_token: str | None = None


@router.get("/me")
def me(identity: Identity = IdentityDep) -> dict[str, object]:
    return {
        "user_id": identity.user_id,
        "username": identity.user_id,
        "tenant_id": identity.tenant_id,
        "roles": identity.roles,
    }


def _normalize_username(value: str) -> str:
    return value.strip().lower()


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _default_email_for_username(username: str) -> str:
    if "@" in username:
        return _normalize_email(username)
    return f"{username}@local.invalid"


def _refresh_secret(cfg) -> str:
    return (cfg.auth_refresh_token_secret or cfg.auth_jwt_secret or "").strip()


def _password_reset_secret(cfg) -> str:
    return (cfg.auth_password_reset_secret or cfg.auth_jwt_secret or "").strip()


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
        roles=list_role_names(user),
        secret=cfg.auth_jwt_secret,
        issuer=cfg.auth_jwt_issuer,
        expires_minutes=cfg.auth_access_token_minutes,
    )
    refresh_token = generate_refresh_token()
    refresh_expires = datetime.now(UTC) + timedelta(days=cfg.auth_refresh_token_days)
    return access_token, refresh_token, refresh_expires, cfg.auth_access_token_minutes * 60


async def _persist_refresh_token(
    session: AsyncSession,
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
    await create_refresh_token(
        session,
        tenant_id=user.tenant_id,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=refresh_expires,
    )


async def _mfa_factor(session: AsyncSession, *, user_id) -> AuthMfaFactorRow | None:
    return await get_mfa_factor(session, user_id=user_id, enabled_only=True)


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
        roles=list_role_names(user),
    )


async def _get_user_from_identity(session: AsyncSession, identity: Identity) -> AuthUserRow | None:
    try:
        tenant = tenant_uuid(identity.tenant_id)
    except Exception:
        return None
    return await get_user_by_identity(session, tenant_id=tenant, username=identity.user_id)


@router.post("/auth/register", response_model=AuthTokensOut)
async def register(request: Request, response: Response, body: RegisterIn, session: DBDep) -> AuthTokensOut:
    cfg = get_auth_config()
    if not cfg.auth_allow_register:
        raise HTTPException(status_code=403, detail="Registration disabled")

    username = _normalize_username(body.username)
    email = _normalize_email(body.email) if body.email else _default_email_for_username(username)
    tenant_id = tenant_uuid(body.tenant_id) if body.tenant_id else uuid4()
    password_hash = hash_password(body.password)

    try:
        user = await create_user(
            session=session,
            tenant_id=tenant_id,
            username=username,
            email=email,
            password_hash=password_hash,
            role_names=["owner"],
            is_active=True,
        )
    except IntegrityError as e:
        raise HTTPException(status_code=409, detail="Username already exists") from e

    access_token, refresh_token, refresh_expires, expires_in = _issue_tokens(user)
    await _persist_refresh_token(
        session, user=user, refresh_token=refresh_token, refresh_expires=refresh_expires
    )
    _set_refresh_cookie(
        response,
        refresh_token,
        max_age_seconds=int((refresh_expires - datetime.now(UTC)).total_seconds()),
    )

    return AuthTokensOut(
        access_token=access_token,
        expires_in=expires_in,
        user_id=user.username,
        username=user.username,
        tenant_id=str(user.tenant_id),
        roles=list_role_names(user),
    )


@router.post("/auth/login", response_model=AuthTokensOut)
async def login(request: Request, response: Response, body: LoginIn, session: DBDep) -> AuthTokensOut:
    raw = _normalize_username(body.username)
    user = await get_user_by_username_or_email(session, value=raw)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    mfa_factor = await _mfa_factor(session, user_id=user.id)
    if mfa_factor is not None:
        return _issue_mfa_challenge(user)

    access_token, refresh_token, refresh_expires, expires_in = _issue_tokens(user)
    await _persist_refresh_token(
        session, user=user, refresh_token=refresh_token, refresh_expires=refresh_expires
    )
    _set_refresh_cookie(
        response,
        refresh_token,
        max_age_seconds=int((refresh_expires - datetime.now(UTC)).total_seconds()),
    )

    return AuthTokensOut(
        access_token=access_token,
        expires_in=expires_in,
        user_id=user.username,
        username=user.username,
        tenant_id=str(user.tenant_id),
        roles=list_role_names(user),
    )


@router.post("/auth/refresh", response_model=AuthTokensOut)
async def refresh(request: Request, response: Response, session: DBDep) -> AuthTokensOut:
    cfg = get_auth_config()
    secret = _refresh_secret(cfg)
    if not secret:
        raise HTTPException(status_code=500, detail="Refresh token secret not configured")
    raw = request.cookies.get(cfg.auth_refresh_cookie_name)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing refresh token")
    token_hash = hash_refresh_token(raw, secret=secret)
    now = datetime.now(UTC)

    token_row = await get_refresh_token_by_hash(session, token_hash=token_hash)
    if token_row is None or token_row.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if _utc(token_row.expires_at) <= now:
        raise HTTPException(status_code=401, detail="Refresh token expired")

    user = await get_user_by_id(session, tenant_id=token_row.tenant_id, user_id=token_row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    revoke_refresh_token(token_row, now=now)

    access_token, refresh_token, refresh_expires, expires_in = _issue_tokens(user)
    await _persist_refresh_token(
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
        roles=list_role_names(user),
    )


@router.post("/auth/password/reset/request", response_model=PasswordResetRequestOut)
async def password_reset_request(
    request: Request,
    body: PasswordResetRequestIn,
    session: DBDep,
) -> PasswordResetRequestOut:
    cfg = get_auth_config()
    settings = get_settings()
    secret = _password_reset_secret(cfg)
    if not secret:
        raise HTTPException(status_code=500, detail="Password reset secret not configured")

    email = _normalize_email(body.email)
    logger.info(
        "Password reset requested",
        extra={
            "event": "auth.password_reset.request",
            "email_domain": _email_domain(email),
            "environment": settings.environment,
        },
    )
    reset_token: str | None = None

    user = await get_user_by_email(session, email=email)
    if user is None or not user.is_active:
        logger.info(
            "Password reset request ignored (user not found/inactive)",
            extra={
                "event": "auth.password_reset.request.ignored",
                "email_domain": _email_domain(email),
            },
        )
        return PasswordResetRequestOut(status="ok")

    reset_token = f"{uuid4().int % 1000000:06d}"
    token_hash = hash_password_reset_token(reset_token, secret=secret)
    expires_at = datetime.now(UTC) + timedelta(minutes=cfg.auth_password_reset_minutes)

    await create_password_reset(
        session,
        tenant_id=user.tenant_id,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )

    try:
        send_password_reset_otp(to_email=user.email, otp=reset_token)
        logger.info(
            "Password reset OTP email sent",
            extra={
                "event": "auth.password_reset.otp.sent",
                "email_domain": _email_domain(user.email),
                "environment": settings.environment,
            },
        )
    except RuntimeError as e:
        logger.exception(
            "Password reset OTP email failed",
            extra={
                "event": "auth.password_reset.otp.failed",
                "email_domain": _email_domain(user.email),
                "environment": settings.environment,
                "reason": str(e),
            },
        )
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        logger.exception(
            "Password reset OTP email failed",
            extra={
                "event": "auth.password_reset.otp.failed",
                "email_domain": _email_domain(user.email),
                "environment": settings.environment,
            },
        )
        raise HTTPException(status_code=500, detail="Failed to send reset email") from e
    return PasswordResetRequestOut(status="ok")


@router.post("/auth/password/reset/confirm")
async def password_reset_confirm(request: Request, body: PasswordResetConfirmIn, session: DBDep) -> dict[str, str]:
    cfg = get_auth_config()
    secret = _password_reset_secret(cfg)
    if not secret:
        raise HTTPException(status_code=500, detail="Password reset secret not configured")

    token_hash = hash_password_reset_token(body.token, secret=secret)
    logger.info(
        "Password reset confirm attempted",
        extra={
            "event": "auth.password_reset.confirm",
            "token_len": len(body.token or ""),
            "token_hash_prefix": token_hash[:8],
        },
    )
    now = datetime.now(UTC)

    reset_row = await get_password_reset_by_hash(session, token_hash=token_hash)
    if (
        reset_row is None
        or reset_row.used_at is not None
        or _utc(reset_row.expires_at) <= now
    ):
        logger.warning(
            "Password reset confirm rejected (invalid/expired token)",
            extra={
                "event": "auth.password_reset.confirm.rejected",
                "token_hash_prefix": token_hash[:8],
                "reason": "invalid_or_expired_token",
            },
        )
        raise HTTPException(status_code=401, detail="Invalid or expired reset token")

    user = await get_user_by_id(session, tenant_id=reset_row.tenant_id, user_id=reset_row.user_id)
    if user is None or not user.is_active:
        logger.warning(
            "Password reset confirm rejected (invalid user)",
            extra={
                "event": "auth.password_reset.confirm.rejected",
                "token_hash_prefix": token_hash[:8],
                "reason": "invalid_user",
            },
        )
        raise HTTPException(status_code=401, detail="Invalid or expired reset token")

    user.password_hash = hash_password(body.password)
    reset_row.used_at = now

    await revoke_refresh_tokens_for_user(session, user_id=user.id, now=now)

    logger.info(
        "Password reset confirmed",
        extra={
            "event": "auth.password_reset.confirmed",
            "tenant_id": str(user.tenant_id),
            "user_id": str(user.id),
        },
    )

    return {"status": "ok"}


@router.get("/auth/mfa/status", response_model=MfaStatusOut)
async def mfa_status(request: Request, session: DBDep, identity: Identity = IdentityDep) -> MfaStatusOut:
    user = await _get_user_from_identity(session, identity)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid account")
    factor = await get_mfa_factor(session, user_id=user.id, enabled_only=False)
    enabled = bool(factor and factor.enabled_at)
    pending = bool(factor and not factor.enabled_at)
    return MfaStatusOut(enabled=enabled, pending=pending)


@router.post("/auth/mfa/enroll/start", response_model=MfaEnrollStartOut)
async def mfa_enroll_start(
    request: Request, session: DBDep, identity: Identity = IdentityDep
) -> MfaEnrollStartOut:
    cfg = get_auth_config()
    user = await _get_user_from_identity(session, identity)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid account")
    factor = await get_mfa_factor(session, user_id=user.id, enabled_only=False)
    if factor is not None and factor.enabled_at is not None:
        raise HTTPException(status_code=409, detail="MFA already enabled")

    secret = generate_totp_secret()
    factor = await upsert_mfa_factor(session, user=user, secret=secret)

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
async def mfa_enroll_verify(
    request: Request,
    body: MfaVerifyIn,
    session: DBDep,
    identity: Identity = IdentityDep,
) -> dict[str, object]:
    cfg = get_auth_config()
    user = await _get_user_from_identity(session, identity)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid account")
    factor = await get_mfa_factor(session, user_id=user.id, enabled_only=False)
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
    now = datetime.now(UTC)
    factor.enabled_at = now
    factor.last_used_at = now
    return {"enabled": True}


@router.post("/auth/mfa/disable")
async def mfa_disable(
    request: Request,
    body: MfaVerifyIn,
    session: DBDep,
    identity: Identity = IdentityDep,
) -> dict[str, object]:
    cfg = get_auth_config()
    user = await _get_user_from_identity(session, identity)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid account")
    factor = await get_mfa_factor(session, user_id=user.id, enabled_only=False)
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
    await delete_mfa_factor(session, factor)
    return {"enabled": False}


@router.post("/auth/mfa/verify", response_model=AuthTokensOut)
async def mfa_verify(request: Request, response: Response, body: MfaChallengeIn, session: DBDep) -> AuthTokensOut:
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

    tenant_claim = claims.get("tenant_id")
    if not isinstance(tenant_claim, str) or not tenant_claim:
        raise HTTPException(status_code=401, detail="Invalid MFA token")
    try:
        tenant_uuid_from_claim = UUID(tenant_claim)
    except ValueError as e:
        raise HTTPException(status_code=401, detail="Invalid MFA token") from e

    user = await get_user_by_id(session, tenant_id=tenant_uuid_from_claim, user_id=user_uuid)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid MFA token")
    factor = await _mfa_factor(session, user_id=user.id)
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

    now = datetime.now(UTC)
    factor.last_used_at = now

    access_token, refresh_token, refresh_expires, expires_in = _issue_tokens(user)
    await _persist_refresh_token(
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
        roles=list_role_names(user),
    )


@router.post("/auth/logout")
async def logout(request: Request, response: Response, session: DBDep) -> dict[str, str]:
    cfg = get_auth_config()
    secret = _refresh_secret(cfg)
    raw = request.cookies.get(cfg.auth_refresh_cookie_name)
    if raw and secret:
        token_hash = hash_refresh_token(raw, secret=secret)
        token_row = await get_refresh_token_by_hash(session, token_hash=token_hash)
        if token_row is not None and token_row.revoked_at is None:
            token_row.revoked_at = datetime.now(UTC)
    _clear_refresh_cookie(response)
    return {"status": "ok"}
