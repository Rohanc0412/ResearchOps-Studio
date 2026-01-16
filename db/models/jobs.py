from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base


class JobStatusDb(str, enum.Enum):
    queued = "queued"
    running = "running"
    failed = "failed"
    succeeded = "succeeded"


class JobRow(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_jobs_tenant_id_id"),
        Index("ix_jobs_tenant_run", "tenant_id", "run_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[JobStatusDb] = mapped_column(
        Enum(JobStatusDb, name="job_status"), nullable=False
    )
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


JobRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "run_id"],
        ["runs.tenant_id", "runs.id"],
        ondelete="CASCADE",
        name="fk_jobs_tenant_run",
    )
)
