from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKeyConstraint, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.runs import RunRow
    from db.models.sources import SourceRow


class RunSourceRow(Base):
    __tablename__ = "run_sources"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "source_id",
            name="uq_run_sources_tenant_run_source",
        ),
        Index("ix_run_sources_tenant_run", "tenant_id", "run_id"),
        Index("ix_run_sources_tenant_source", "tenant_id", "source_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    source_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float(), nullable=False, default=0.0, server_default="0")
    origin: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    run: Mapped[RunRow] = relationship("RunRow", overlaps="source")
    source: Mapped[SourceRow] = relationship("SourceRow", overlaps="run")


RunSourceRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "run_id"],
        ["runs.tenant_id", "runs.id"],
        ondelete="CASCADE",
        name="fk_run_sources_tenant_run",
    )
)
RunSourceRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "source_id"],
        ["sources.tenant_id", "sources.id"],
        ondelete="CASCADE",
        name="fk_run_sources_tenant_source",
    )
)
