from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.runs import RunRow
    from db.models.snippets import SnippetRow


class SectionEvidenceRow(Base):
    __tablename__ = "section_evidence"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "section_id",
            "snippet_id",
            name="uq_section_evidence_tenant_run_section_snippet",
        ),
        Index("ix_section_evidence_tenant_section", "tenant_id", "run_id", "section_id"),
        Index("ix_section_evidence_tenant_snippet", "tenant_id", "snippet_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    section_id: Mapped[str] = mapped_column(String(100), nullable=False)
    snippet_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    run: Mapped[RunRow] = relationship("RunRow", overlaps="section_evidence")
    snippet: Mapped[SnippetRow] = relationship("SnippetRow", overlaps="evidence_sections")


SectionEvidenceRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "run_id"],
        ["runs.tenant_id", "runs.id"],
        ondelete="CASCADE",
        name="fk_section_evidence_tenant_run",
    )
)
SectionEvidenceRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "snippet_id"],
        ["snippets.tenant_id", "snippets.id"],
        ondelete="CASCADE",
        name="fk_section_evidence_tenant_snippet",
    )
)
