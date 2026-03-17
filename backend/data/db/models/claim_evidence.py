from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.claim_map import ClaimMapRow
    from db.models.snippets import SnippetRow


class ClaimEvidenceRow(Base):
    __tablename__ = "claim_evidence"
    __table_args__ = (
        UniqueConstraint("tenant_id", "claim_id", "snippet_id", name="uq_claim_evidence_link"),
        Index("ix_claim_evidence_tenant_claim", "tenant_id", "claim_id"),
        Index("ix_claim_evidence_tenant_snippet", "tenant_id", "snippet_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    snippet_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    claim: Mapped[ClaimMapRow] = relationship(
        "ClaimMapRow", back_populates="evidence_links", overlaps="snippet"
    )
    snippet: Mapped[SnippetRow] = relationship("SnippetRow", overlaps="claim,evidence_links")


ClaimEvidenceRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "claim_id"],
        ["claim_map.tenant_id", "claim_map.id"],
        ondelete="CASCADE",
        name="fk_claim_evidence_claim",
    )
)
ClaimEvidenceRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "snippet_id"],
        ["snippets.tenant_id", "snippets.id"],
        ondelete="CASCADE",
        name="fk_claim_evidence_snippet",
    )
)
