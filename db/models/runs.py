from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base


class RunStatusDb(str, enum.Enum):
    created = "created"
    queued = "queued"
    running = "running"
    failed = "failed"
    succeeded = "succeeded"


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    status: Mapped[RunStatusDb] = mapped_column(Enum(RunStatusDb, name="run_status"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
