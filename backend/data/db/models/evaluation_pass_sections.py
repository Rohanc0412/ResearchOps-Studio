from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.sqltypes import JSON

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.evaluation_passes import EvaluationPassRow


class EvaluationPassSectionRow(Base):
    __tablename__ = "evaluation_pass_sections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_evaluation_pass_sections_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "evaluation_pass_id",
            "section_id",
            name="uq_evaluation_pass_sections_tenant_pass_section",
        ),
        Index("ix_evaluation_pass_sections_tenant_pass", "tenant_id", "evaluation_pass_id"),
        Index(
            "ix_evaluation_pass_sections_tenant_pass_order",
            "tenant_id",
            "evaluation_pass_id",
            "section_order",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    evaluation_pass_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    section_id: Mapped[str] = mapped_column(String(100), nullable=False)
    section_title: Mapped[str | None] = mapped_column(Text(), nullable=True)
    section_order: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    verdict: Mapped[str] = mapped_column(String(10), nullable=False)
    grounding_score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    issues_json: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list, server_default="[]"
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

    evaluation_pass: Mapped[EvaluationPassRow] = relationship("EvaluationPassRow", back_populates="sections")


EvaluationPassSectionRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "evaluation_pass_id"],
        ["evaluation_passes.tenant_id", "evaluation_passes.id"],
        ondelete="CASCADE",
        name="fk_evaluation_pass_sections_tenant_pass",
    )
)
