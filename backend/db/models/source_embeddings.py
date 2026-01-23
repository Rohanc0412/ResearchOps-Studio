from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import JSON

from db.models.base import Base


class SourceEmbeddingRow(Base):
    __tablename__ = "source_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "canonical_id",
            "embedding_model",
            name="uq_source_embeddings_tenant_canonical_model",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_source_embeddings_tenant_id_id"),
        Index("ix_source_embeddings_tenant_model", "tenant_id", "embedding_model"),
        Index("ix_source_embeddings_tenant_canonical", "tenant_id", "canonical_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    canonical_id: Mapped[str] = mapped_column(String(500), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer(), nullable=False)
    embedding_json: Mapped[list[float]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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
