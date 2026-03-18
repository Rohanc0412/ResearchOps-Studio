from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.roles import UserRoleRow


class AuthUserRow(Base):
    __tablename__ = "auth_users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_auth_users_tenant_id_id"),
        UniqueConstraint("username", name="uq_auth_users_username"),
        UniqueConstraint("email", name="uq_auth_users_email"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )
    user_roles: Mapped[list[UserRoleRow]] = relationship(
        "UserRoleRow", back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def roles_json(self) -> list[str]:
        return [link.role_name for link in sorted(self.user_roles, key=lambda row: row.role_name)]

    @roles_json.setter
    def roles_json(self, values: list[str]) -> None:
        unique_values = []
        seen: set[str] = set()
        for value in values or []:
            role_name = str(value).strip().lower()
            if not role_name or role_name in seen:
                continue
            seen.add(role_name)
            unique_values.append(role_name)
        from db.models.roles import UserRoleRow

        self.user_roles = [
            UserRoleRow(tenant_id=self.tenant_id, role_name=role_name)
            for role_name in unique_values
        ]
