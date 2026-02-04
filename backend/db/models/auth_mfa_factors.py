from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base


class AuthMfaFactorRow(Base):
    __tablename__ = "auth_mfa_factors"
    __table_args__ = (
        UniqueConstraint("user_id", "factor_type", name="uq_auth_mfa_factors_user_type"),
        Index("ix_auth_mfa_factors_user_id", "user_id"),
        Index("ix_auth_mfa_factors_tenant_id", "tenant_id"),
        Index("ix_auth_mfa_factors_enabled_at", "enabled_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    factor_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="totp")
    secret: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
