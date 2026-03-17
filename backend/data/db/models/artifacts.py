from __future__ import annotations

from typing import TYPE_CHECKING
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.sqltypes import JSON

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.projects import ProjectRow
    from db.models.runs import RunRow


class ArtifactRow(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_artifacts_tenant_id_id"),
        Index("ix_artifacts_tenant_project_created_at", "tenant_id", "project_id", "created_at"),
        Index("ix_artifacts_tenant_run_created_at", "tenant_id", "run_id", "created_at"),
        Index("ix_artifacts_tenant_type_created_at", "tenant_id", "type", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    run_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    artifact_type: Mapped[str] = mapped_column("type", String(100), nullable=False)
    blob_ref: Mapped[str] = mapped_column(String(1000), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(200), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    project: Mapped[ProjectRow] = relationship(
        "ProjectRow", back_populates="artifacts", overlaps="run"
    )
    run: Mapped[RunRow | None] = relationship(
        "RunRow", back_populates="artifacts", overlaps="project"
    )


ArtifactRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        ["projects.tenant_id", "projects.id"],
        ondelete="CASCADE",
        name="fk_artifacts_tenant_project",
    )
)
ArtifactRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "run_id"],
        ["runs.tenant_id", "runs.id"],
        ondelete="SET NULL",
        name="fk_artifacts_tenant_run",
    )
)
