from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING
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
    from db.models.claim_evidence import ClaimEvidenceRow
    from db.models.projects import ProjectRow
    from db.models.runs import RunRow


class ClaimVerdictDb(str, enum.Enum):
    supported = "supported"
    unsupported = "unsupported"
    partially_supported = "partially_supported"
    needs_citation = "needs_citation"


class ClaimMapRow(Base):
    __tablename__ = "claim_map"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_claim_map_tenant_id_id"),
        Index("ix_claim_map_tenant_run_created_at", "tenant_id", "run_id", "created_at"),
        Index("ix_claim_map_tenant_project_created_at", "tenant_id", "project_id", "created_at"),
        Index("ix_claim_map_tenant_claim_hash", "tenant_id", "claim_hash"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    claim_text: Mapped[str] = mapped_column(Text(), nullable=False)
    claim_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verdict: Mapped[ClaimVerdictDb] = mapped_column(
        Enum(ClaimVerdictDb, name="claim_verdict"), nullable=False
    )
    explanation: Mapped[str | None] = mapped_column(Text(), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    project: Mapped[ProjectRow] = relationship(  # type: ignore[name-defined]
        "ProjectRow", back_populates="claim_map_entries", overlaps="run"
    )
    run: Mapped[RunRow] = relationship(  # type: ignore[name-defined]
        "RunRow", back_populates="claim_map_entries", overlaps="project"
    )
    evidence_links: Mapped[list[ClaimEvidenceRow]] = relationship(
        "ClaimEvidenceRow",
        back_populates="claim",
        cascade="all, delete-orphan",
        overlaps="snippet",
    )

    @property
    def snippet_ids_json(self) -> list[str]:
        return [str(link.snippet_id) for link in self.evidence_links]

    @snippet_ids_json.setter
    def snippet_ids_json(self, values: list[str]) -> None:
        from db.models.claim_evidence import ClaimEvidenceRow

        self.evidence_links = [
            ClaimEvidenceRow(tenant_id=self.tenant_id, snippet_id=UUID(str(snippet_id)))
            for snippet_id in (values or [])
        ]


ClaimMapRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        ["projects.tenant_id", "projects.id"],
        ondelete="CASCADE",
        name="fk_claim_map_tenant_project",
    )
)
ClaimMapRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "run_id"],
        ["runs.tenant_id", "runs.id"],
        ondelete="CASCADE",
        name="fk_claim_map_tenant_run",
    )
)
