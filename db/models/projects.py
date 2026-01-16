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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.artifacts import ArtifactRow
    from db.models.claim_map import ClaimMapRow
    from db.models.runs import RunRow


class ProjectLastRunStatusDb(str, enum.Enum):
    created = "created"
    queued = "queued"
    running = "running"
    failed = "failed"
    succeeded = "succeeded"
    canceled = "canceled"


class ProjectRow(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_projects_tenant_name"),
        UniqueConstraint("tenant_id", "id", name="uq_projects_tenant_id_id"),
        Index("ix_projects_tenant_created_at", "tenant_id", "created_at"),
        Index("ix_projects_tenant_last_activity_at", "tenant_id", "last_activity_at"),
        Index("ix_projects_tenant_name", "tenant_id", "name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
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

    last_run_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    last_run_status: Mapped[ProjectLastRunStatusDb | None] = mapped_column(
        Enum(ProjectLastRunStatusDb, name="project_last_run_status"), nullable=True
    )
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    runs: Mapped[list[RunRow]] = relationship(
        "RunRow",
        back_populates="project",
        cascade="all, delete-orphan",
        primaryjoin=(
            "and_(ProjectRow.tenant_id==RunRow.tenant_id, "
            "ProjectRow.id==RunRow.project_id)"
        ),
        foreign_keys="[RunRow.tenant_id, RunRow.project_id]",
    )
    artifacts: Mapped[list[ArtifactRow]] = relationship(
        "ArtifactRow", back_populates="project", cascade="all, delete-orphan", overlaps="run"
    )
    claim_map_entries: Mapped[list[ClaimMapRow]] = relationship(
        "ClaimMapRow", back_populates="project", cascade="all, delete-orphan", overlaps="run"
    )


ProjectRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "last_run_id"],
        ["runs.tenant_id", "runs.id"],
        ondelete="SET NULL",
        name="fk_projects_last_run",
        use_alter=True,
    )
)
