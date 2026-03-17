from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
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
    from db.models.snippets import SnippetRow
    from db.models.sources import SourceRow


class SnapshotRow(Base):
    __tablename__ = "snapshots"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "source_id", "snapshot_version", name="uq_snapshots_tenant_source_version"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_snapshots_tenant_id_id"),
        Index("ix_snapshots_tenant_source_version", "tenant_id", "source_id", "snapshot_version"),
        Index("ix_snapshots_tenant_source_retrieved_at", "tenant_id", "source_id", "retrieved_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    source_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    snapshot_version: Mapped[int] = mapped_column(Integer(), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    content_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    blob_ref: Mapped[str] = mapped_column(String(1000), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict, server_default="{}"
    )

    source: Mapped[SourceRow] = relationship("SourceRow", back_populates="snapshots")
    snippets: Mapped[list[SnippetRow]] = relationship(
        "SnippetRow", back_populates="snapshot", cascade="all, delete-orphan"
    )


SnapshotRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "source_id"],
        ["sources.tenant_id", "sources.id"],
        ondelete="CASCADE",
        name="fk_snapshots_tenant_source",
    )
)
