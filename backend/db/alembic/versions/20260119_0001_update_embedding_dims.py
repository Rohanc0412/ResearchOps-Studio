"""Update snippet_embeddings vector dimension to 1024 for local BGE embeddings.

Revision ID: 20260119_0001
Revises: 20260117_0001
Create Date: 2026-01-19
"""

from __future__ import annotations

from alembic import op
from pgvector.sqlalchemy import Vector


revision = "20260119_0001"
down_revision = "20260117_0001"
branch_labels = None
depends_on = None

_NEW_DIMS = 1024
_OLD_DIMS = 1536


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_snippet_embeddings_embedding_ivfflat")
    # Reset embeddings so we can re-embed with the new dimensionality.
    op.execute("DELETE FROM snippet_embeddings")
    op.alter_column(
        "snippet_embeddings",
        "embedding",
        type_=Vector(_NEW_DIMS),
        existing_nullable=False,
    )
    op.create_index(
        "ix_snippet_embeddings_embedding_ivfflat",
        "snippet_embeddings",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"lists": 100},
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_snippet_embeddings_embedding_ivfflat")
    op.execute("DELETE FROM snippet_embeddings")
    op.alter_column(
        "snippet_embeddings",
        "embedding",
        type_=Vector(_OLD_DIMS),
        existing_nullable=False,
    )
    op.create_index(
        "ix_snippet_embeddings_embedding_ivfflat",
        "snippet_embeddings",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"lists": 100},
    )
