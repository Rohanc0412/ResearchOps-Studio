from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes, selectinload

from db.models.auth_mfa_factors import AuthMfaFactorRow
from db.models.auth_password_resets import AuthPasswordResetRow
from db.models.auth_refresh_tokens import AuthRefreshTokenRow
from db.models.auth_users import AuthUserRow
from db.models.roles import RoleRow, UserRoleRow

DEFAULT_ROLE_NAMES = ("owner", "admin", "researcher", "viewer")


async def ensure_default_roles(session: AsyncSession) -> None:
    existing = {row[0] for row in (await session.execute(select(RoleRow.name))).all()}
    for role_name in DEFAULT_ROLE_NAMES:
        if role_name in existing:
            continue
        session.add(RoleRow(name=role_name, description=f"Built-in {role_name} role"))


async def assign_roles(session: AsyncSession, user: AuthUserRow, role_names: list[str]) -> None:
    await ensure_default_roles(session)
    unique = []
    seen: set[str] = set()
    for value in role_names:
        role_name = str(value).strip().lower()
        if not role_name or role_name in seen:
            continue
        seen.add(role_name)
        unique.append(role_name)
    new_roles = [
        UserRoleRow(tenant_id=user.tenant_id, role_name=role_name)
        for role_name in unique
    ]
    # Use set_committed_value to bypass lazy-load in async context: the collection
    # is being replaced wholesale (not merged), so we can safely mark it as "loaded"
    # with an empty list first, then assign the new rows without triggering a SELECT.
    attributes.set_committed_value(user, "user_roles", [])
    user.user_roles = new_roles


def list_role_names(user: AuthUserRow) -> list[str]:
    return [link.role_name for link in sorted(user.user_roles, key=lambda row: row.role_name)]


async def create_user(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    username: str,
    email: str,
    password_hash: str,
    role_names: list[str],
    is_active: bool = True,
) -> AuthUserRow:
    user = AuthUserRow(
        tenant_id=tenant_id,
        username=username,
        email=email,
        password_hash=password_hash,
        is_active=is_active,
    )
    session.add(user)
    await session.flush()
    await assign_roles(session, user, role_names)
    await session.flush()
    return user


async def get_user_by_id(session: AsyncSession, *, tenant_id: UUID, user_id: UUID) -> AuthUserRow | None:
    stmt = (
        select(AuthUserRow)
        .where(AuthUserRow.tenant_id == tenant_id, AuthUserRow.id == user_id)
        .options(selectinload(AuthUserRow.user_roles))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_user_by_username(session: AsyncSession, *, username: str) -> AuthUserRow | None:
    stmt = (
        select(AuthUserRow)
        .where(AuthUserRow.username == username)
        .options(selectinload(AuthUserRow.user_roles))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_user_by_email(session: AsyncSession, *, email: str) -> AuthUserRow | None:
    stmt = (
        select(AuthUserRow)
        .where(AuthUserRow.email == email)
        .options(selectinload(AuthUserRow.user_roles))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_user_by_username_or_email(session: AsyncSession, *, value: str) -> AuthUserRow | None:
    if "@" in value:
        return await get_user_by_email(session, email=value)
    return await get_user_by_username(session, username=value)


async def get_user_by_identity(
    session: AsyncSession, *, tenant_id: UUID, username: str
) -> AuthUserRow | None:
    stmt = (
        select(AuthUserRow)
        .where(AuthUserRow.username == username, AuthUserRow.tenant_id == tenant_id)
        .options(selectinload(AuthUserRow.user_roles))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_refresh_token(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    token_hash: str,
    expires_at: datetime,
) -> AuthRefreshTokenRow:
    row = AuthRefreshTokenRow(
        tenant_id=tenant_id,
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    session.add(row)
    await session.flush()
    return row


async def get_refresh_token_by_hash(session: AsyncSession, *, token_hash: str) -> AuthRefreshTokenRow | None:
    stmt = select(AuthRefreshTokenRow).where(AuthRefreshTokenRow.token_hash == token_hash)
    return (await session.execute(stmt)).scalar_one_or_none()


def revoke_refresh_token(row: AuthRefreshTokenRow, *, now: datetime) -> None:
    row.revoked_at = now
    row.last_used_at = now


async def revoke_refresh_tokens_for_user(session: AsyncSession, *, user_id: UUID, now: datetime) -> None:
    await session.execute(
        update(AuthRefreshTokenRow)
        .where(
            AuthRefreshTokenRow.user_id == user_id,
            AuthRefreshTokenRow.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )


async def create_password_reset(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    token_hash: str,
    expires_at: datetime,
) -> AuthPasswordResetRow:
    row = AuthPasswordResetRow(
        tenant_id=tenant_id,
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    session.add(row)
    await session.flush()
    return row


async def get_password_reset_by_hash(
    session: AsyncSession, *, token_hash: str
) -> AuthPasswordResetRow | None:
    stmt = select(AuthPasswordResetRow).where(AuthPasswordResetRow.token_hash == token_hash)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_mfa_factor(
    session: AsyncSession, *, user_id: UUID, enabled_only: bool = False
) -> AuthMfaFactorRow | None:
    stmt = select(AuthMfaFactorRow).where(
        AuthMfaFactorRow.user_id == user_id,
        AuthMfaFactorRow.factor_type == "totp",
    )
    if enabled_only:
        stmt = stmt.where(AuthMfaFactorRow.enabled_at.is_not(None))
    return (await session.execute(stmt)).scalar_one_or_none()


async def upsert_mfa_factor(session: AsyncSession, *, user: AuthUserRow, secret: str) -> AuthMfaFactorRow:
    factor = await get_mfa_factor(session, user_id=user.id, enabled_only=False)
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
    await session.flush()
    return factor


async def delete_mfa_factor(session: AsyncSession, factor: AuthMfaFactorRow) -> None:
    await session.delete(factor)


__all__ = [
    "DEFAULT_ROLE_NAMES",
    "assign_roles",
    "create_password_reset",
    "create_refresh_token",
    "create_user",
    "delete_mfa_factor",
    "ensure_default_roles",
    "get_mfa_factor",
    "get_password_reset_by_hash",
    "get_refresh_token_by_hash",
    "get_user_by_email",
    "get_user_by_id",
    "get_user_by_identity",
    "get_user_by_username",
    "get_user_by_username_or_email",
    "list_role_names",
    "revoke_refresh_token",
    "revoke_refresh_tokens_for_user",
    "upsert_mfa_factor",
]
