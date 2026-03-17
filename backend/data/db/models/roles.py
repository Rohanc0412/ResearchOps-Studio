from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.auth_users import AuthUserRow


class RoleRow(Base):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("name", name="uq_roles_name"),
        Index("ix_roles_name", "name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserRoleRow(Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "role_name", name="uq_user_roles_user_role"),
        Index("ix_user_roles_tenant_user", "tenant_id", "user_id"),
        Index("ix_user_roles_role_name", "role_name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    role_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[AuthUserRow] = relationship("AuthUserRow", back_populates="user_roles")
    role: Mapped[RoleRow] = relationship("RoleRow")


UserRoleRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "user_id"],
        ["auth_users.tenant_id", "auth_users.id"],
        ondelete="CASCADE",
        name="fk_user_roles_user",
    )
)
UserRoleRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["role_name"],
        ["roles.name"],
        ondelete="CASCADE",
        name="fk_user_roles_role",
    )
)
