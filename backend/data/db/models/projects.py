from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
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


class ProjectRow(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_projects_tenant_name"),
        UniqueConstraint("tenant_id", "id", name="uq_projects_tenant_id_id"),
        Index("ix_projects_tenant_created_at", "tenant_id", "created_at"),
        Index("ix_projects_tenant_updated_at", "tenant_id", "updated_at"),
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

    @property
    def last_run(self) -> RunRow | None:  # type: ignore[name-defined]
        if not self.runs:
            return None
        return max(self.runs, key=lambda row: row.created_at)

    @property
    def last_run_id(self) -> UUID | None:
        row = self.last_run
        return row.id if row else None

    @property
    def last_run_status(self) -> str | None:
        row = self.last_run
        return row.status.value if row else None

    @property
    def last_activity_at(self) -> datetime | None:
        row = self.last_run
        if row and row.updated_at:
            return row.updated_at
        return self.updated_at
