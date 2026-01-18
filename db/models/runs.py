from __future__ import annotations

import enum
from typing import TYPE_CHECKING
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.sqltypes import JSON

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.artifacts import ArtifactRow
    from db.models.claim_map import ClaimMapRow
    from db.models.projects import ProjectRow
    from db.models.run_events import RunEventRow


class RunStatusDb(str, enum.Enum):
    created = "created"
    queued = "queued"
    running = "running"
    blocked = "blocked"
    failed = "failed"
    succeeded = "succeeded"
    canceled = "canceled"


class RunRow(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_runs_tenant_id_id"),
        Index("ix_runs_tenant_project_created_at", "tenant_id", "project_id", "created_at"),
        Index("ix_runs_tenant_status_created_at", "tenant_id", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    status: Mapped[RunStatusDb] = mapped_column(
        Enum(RunStatusDb, name="run_status"), nullable=False
    )
    current_stage: Mapped[str | None] = mapped_column(String(200), nullable=True)
    budgets_json: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict, server_default="{}"
    )
    usage_json: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict, server_default="{}"
    )
    failure_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_count: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
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

    project: Mapped[ProjectRow] = relationship(
        "ProjectRow",
        back_populates="runs",
        primaryjoin=(
            "and_(RunRow.tenant_id==ProjectRow.tenant_id, "
            "RunRow.project_id==ProjectRow.id)"
        ),
        foreign_keys="[RunRow.tenant_id, RunRow.project_id]",
    )
    events: Mapped[list[RunEventRow]] = relationship(
        "RunEventRow", back_populates="run", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list[ArtifactRow]] = relationship(
        "ArtifactRow", back_populates="run", overlaps="project,artifacts"
    )
    claim_map_entries: Mapped[list[ClaimMapRow]] = relationship(
        "ClaimMapRow",
        back_populates="run",
        cascade="all, delete-orphan",
        overlaps="project,claim_map_entries",
    )


RunRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        ["projects.tenant_id", "projects.id"],
        ondelete="CASCADE",
        name="fk_runs_tenant_project",
    )
)
