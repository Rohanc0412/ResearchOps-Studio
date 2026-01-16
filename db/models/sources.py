from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.sqltypes import JSON

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.snapshots import SnapshotRow


class SourceRow(Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("tenant_id", "canonical_id", name="uq_sources_tenant_canonical"),
        UniqueConstraint("tenant_id", "id", name="uq_sources_tenant_id_id"),
        Index("ix_sources_tenant_type_year", "tenant_id", "source_type", "year"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    canonical_id: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str | None] = mapped_column(Text(), nullable=True)
    authors_json: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list, server_default="[]"
    )
    year: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    url: Mapped[str | None] = mapped_column(Text(), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict, server_default="{}"
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

    snapshots: Mapped[list[SnapshotRow]] = relationship(
        "SnapshotRow", back_populates="source", cascade="all, delete-orphan"
    )
