"""Cached atomic claims extracted from section text by RAGAS."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base


class SectionClaimRow(Base):
    __tablename__ = "section_claims"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    section_id: Mapped[str] = mapped_column(String(100), nullable=False)
    claim_index: Mapped[int] = mapped_column(Integer(), nullable=False)
    claim_text: Mapped[str] = mapped_column(Text(), nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "run_id", "section_id", "claim_index",
            name="uq_section_claims_position",
        ),
        Index("ix_section_claims_lookup", "tenant_id", "run_id", "section_id"),
    )
