from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.section_reviews import SectionReviewRow


class SectionReviewIssueRow(Base):
    __tablename__ = "section_review_issues"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_section_review_issues_tenant_id_id"),
        UniqueConstraint("tenant_id", "review_id", "issue_order", name="uq_section_review_issues_order"),
        Index("ix_section_review_issues_tenant_review", "tenant_id", "review_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    review_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    issue_order: Mapped[int] = mapped_column(Integer(), nullable=False)
    sentence_index: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    problem: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    review: Mapped[SectionReviewRow] = relationship("SectionReviewRow", back_populates="issues")
    citations: Mapped[list[SectionReviewIssueCitationRow]] = relationship(  # type: ignore[name-defined]
        "SectionReviewIssueCitationRow", back_populates="issue", cascade="all, delete-orphan"
    )


class SectionReviewIssueCitationRow(Base):
    __tablename__ = "section_review_issue_citations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "issue_id", "snippet_id", name="uq_section_review_issue_citation"),
        Index("ix_section_review_issue_citations_tenant_issue", "tenant_id", "issue_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    issue_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    snippet_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    issue: Mapped[SectionReviewIssueRow] = relationship(
        "SectionReviewIssueRow", back_populates="citations"
    )


SectionReviewIssueRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "review_id"],
        ["section_reviews.tenant_id", "section_reviews.id"],
        ondelete="CASCADE",
        name="fk_section_review_issues_review",
    )
)
SectionReviewIssueCitationRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "issue_id"],
        ["section_review_issues.tenant_id", "section_review_issues.id"],
        ondelete="CASCADE",
        name="fk_section_review_issue_citations_issue",
    )
)
SectionReviewIssueCitationRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "snippet_id"],
        ["snippets.tenant_id", "snippets.id"],
        ondelete="CASCADE",
        name="fk_section_review_issue_citations_snippet",
    )
)
