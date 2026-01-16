from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.sqltypes import JSON

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.snippets import SnippetRow


_EMBEDDING_DIMS = 1536


class SnippetEmbeddingRow(Base):
    __tablename__ = "snippet_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "snippet_id",
            "embedding_model",
            name="uq_snippet_embeddings_tenant_snippet_model",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_snippet_embeddings_tenant_id_id"),
        Index("ix_snippet_embeddings_tenant_snippet", "tenant_id", "snippet_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    snippet_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    dims: Mapped[int] = mapped_column(Integer(), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        JSON().with_variant(Vector(_EMBEDDING_DIMS), "postgresql"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    snippet: Mapped[SnippetRow] = relationship("SnippetRow", back_populates="embeddings")


SnippetEmbeddingRow.__table__.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "snippet_id"],
        ["snippets.tenant_id", "snippets.id"],
        ondelete="CASCADE",
        name="fk_snippet_embeddings_tenant_snippet",
    )
)
