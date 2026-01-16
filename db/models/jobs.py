from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base


class JobStatusDb(str, enum.Enum):
    queued = "queued"
    running = "running"
    failed = "failed"
    succeeded = "succeeded"


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[JobStatusDb] = mapped_column(Enum(JobStatusDb, name="job_status"), nullable=False)
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
