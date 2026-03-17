from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.runs import RunRow


class RunStatusTransitionRow(Base):
    __tablename__ = "run_status_transitions"
    __table_args__ = (
        Index("ix_run_status_transitions_tenant_run", "tenant_id", "run_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    to_status: Mapped[str] = mapped_column(String(50), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped[RunRow] = relationship("RunRow", back_populates="status_transitions")


RunStatusTransitionRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "run_id"],
        ["runs.tenant_id", "runs.id"],
        ondelete="CASCADE",
        name="fk_run_status_transitions_run",
    )
)
