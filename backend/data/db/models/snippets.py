from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
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
    from db.models.snapshots import SnapshotRow
    from db.models.snippet_embeddings import SnippetEmbeddingRow


class SnippetRow(Base):
    __tablename__ = "snippets"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "snapshot_id", "snippet_index", name="uq_snippets_tenant_snapshot_index"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_snippets_tenant_id_id"),
        Index("ix_snippets_tenant_snapshot_index", "tenant_id", "snapshot_id", "snippet_index"),
        Index("ix_snippets_tenant_snapshot", "tenant_id", "snapshot_id"),
        Index("ix_snippets_tenant_sha256", "tenant_id", "sha256"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    snapshot_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    snippet_index: Mapped[int] = mapped_column(Integer(), nullable=False)
    text: Mapped[str] = mapped_column(Text(), nullable=False)
    char_start: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_flags_json: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    snapshot: Mapped[SnapshotRow] = relationship("SnapshotRow", back_populates="snippets")
    embeddings: Mapped[list[SnippetEmbeddingRow]] = relationship(
        "SnippetEmbeddingRow", back_populates="snippet", cascade="all, delete-orphan"
    )


SnippetRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "snapshot_id"],
        ["snapshots.tenant_id", "snapshots.id"],
        ondelete="CASCADE",
        name="fk_snippets_tenant_snapshot",
    )
)
