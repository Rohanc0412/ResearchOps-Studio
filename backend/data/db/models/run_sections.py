from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.runs import RunRow


class RunSectionRow(Base):
    __tablename__ = "run_sections"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "section_id",
            name="uq_run_sections_tenant_run_section",
        ),
        Index("ix_run_sections_tenant_run", "tenant_id", "run_id"),
        Index("ix_run_sections_tenant_order", "tenant_id", "run_id", "section_order"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    section_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(Text(), nullable=False)
    goal: Mapped[str] = mapped_column(Text(), nullable=False)
    section_order: Mapped[int] = mapped_column(Integer(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    run: Mapped[RunRow] = relationship("RunRow", overlaps="sections")


RunSectionRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "run_id"],
        ["runs.tenant_id", "runs.id"],
        ondelete="CASCADE",
        name="fk_run_sections_tenant_run",
    )
)
