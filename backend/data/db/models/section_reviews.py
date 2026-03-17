from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, String, Text, UniqueConstraint, Uuid, func
from typing import TYPE_CHECKING

from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.runs import RunRow
    from db.models.section_review_issues import SectionReviewIssueRow


class SectionReviewRow(Base):
    __tablename__ = "section_reviews"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "section_id",
            name="uq_section_reviews_tenant_run_section",
        ),
        Index("ix_section_reviews_tenant_run", "tenant_id", "run_id"),
        Index("ix_section_reviews_tenant_section", "tenant_id", "run_id", "section_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    section_id: Mapped[str] = mapped_column(String(100), nullable=False)
    verdict: Mapped[str] = mapped_column(String(10), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
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

    run: Mapped[RunRow] = relationship("RunRow", overlaps="section_reviews")
    issues: Mapped[list[SectionReviewIssueRow]] = relationship(
        "SectionReviewIssueRow", back_populates="review", cascade="all, delete-orphan"
    )

    @property
    def issues_json(self) -> list[dict]:
        items: list[dict] = []
        for issue in sorted(self.issues, key=lambda row: row.issue_order):
            items.append(
                {
                    "sentence_index": issue.sentence_index,
                    "problem": issue.problem,
                    "notes": issue.notes or "",
                    "citations": [str(citation.snippet_id) for citation in issue.citations],
                }
            )
        return items

    @issues_json.setter
    def issues_json(self, values: list[dict]) -> None:
        from db.models.section_review_issues import (
            SectionReviewIssueCitationRow,
            SectionReviewIssueRow,
        )

        self.issues = []
        for index, item in enumerate(values or []):
            issue_row = SectionReviewIssueRow(
                tenant_id=self.tenant_id,
                issue_order=index,
                sentence_index=int(item.get("sentence_index") or 0),
                problem=str(item.get("problem") or ""),
                notes=str(item.get("notes") or "") or None,
            )
            issue_row.citations = [
                SectionReviewIssueCitationRow(
                    tenant_id=self.tenant_id,
                    snippet_id=UUID(str(snippet_id)),
                )
                for snippet_id in (item.get("citations") or [])
            ]
            self.issues.append(issue_row)


SectionReviewRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "run_id"],
        ["runs.tenant_id", "runs.id"],
        ondelete="CASCADE",
        name="fk_section_reviews_tenant_run",
    )
)
