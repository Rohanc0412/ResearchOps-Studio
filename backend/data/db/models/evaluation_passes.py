from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.sqltypes import JSON

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.evaluation_pass_sections import EvaluationPassSectionRow
    from db.models.runs import RunRow


class EvaluationPassRow(Base):
    __tablename__ = "evaluation_passes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_evaluation_passes_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "scope",
            "pass_index",
            name="uq_evaluation_passes_tenant_run_scope_index",
        ),
        Index("ix_evaluation_passes_tenant_run", "tenant_id", "run_id"),
        Index("ix_evaluation_passes_tenant_run_scope", "tenant_id", "run_id", "scope"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    pass_index: Mapped[int] = mapped_column(Integer(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", server_default="running")
    grounding_pct: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    faithfulness_pct: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    sections_passed: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    sections_total: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    issues_by_type_json: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict, server_default="{}"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
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

    run: Mapped[RunRow] = relationship("RunRow")
    sections: Mapped[list[EvaluationPassSectionRow]] = relationship(
        "EvaluationPassSectionRow", back_populates="evaluation_pass", cascade="all, delete-orphan"
    )


EvaluationPassRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "run_id"],
        ["runs.tenant_id", "runs.id"],
        ondelete="CASCADE",
        name="fk_evaluation_passes_tenant_run",
    )
)
