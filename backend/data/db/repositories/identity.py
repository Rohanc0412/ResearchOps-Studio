from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models.auth_users import AuthUserRow
from db.models.roles import RoleRow, UserRoleRow


DEFAULT_ROLE_NAMES = ("owner", "admin", "researcher", "viewer")


def ensure_default_roles(session: Session) -> None:
    existing = {row[0] for row in session.execute(select(RoleRow.name)).all()}
    for role_name in DEFAULT_ROLE_NAMES:
        if role_name in existing:
            continue
        session.add(RoleRow(name=role_name, description=f"Built-in {role_name} role"))


def assign_roles(session: Session, user: AuthUserRow, role_names: list[str]) -> None:
    ensure_default_roles(session)
    unique = []
    seen: set[str] = set()
    for value in role_names:
        role_name = str(value).strip().lower()
        if not role_name or role_name in seen:
            continue
        seen.add(role_name)
        unique.append(role_name)
    user.user_roles = [
        UserRoleRow(tenant_id=user.tenant_id, role_name=role_name)
        for role_name in unique
    ]


def list_role_names(user: AuthUserRow) -> list[str]:
    return [link.role_name for link in user.user_roles]


__all__ = ["DEFAULT_ROLE_NAMES", "assign_roles", "ensure_default_roles", "list_role_names"]
