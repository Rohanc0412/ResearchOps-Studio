"""Use canonical_id for source embeddings cache.

Revision ID: 20260123_0002
Revises: 20260123_0001
Create Date: 2026-01-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260123_0002"
down_revision = "20260123_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("source_embeddings", sa.Column("canonical_id", sa.String(length=500), nullable=True))
    op.execute(
        """
        UPDATE source_embeddings
        SET canonical_id = sources.canonical_id
        FROM sources
        WHERE source_embeddings.tenant_id = sources.tenant_id
          AND source_embeddings.source_id = sources.id
        """
    )
    op.alter_column("source_embeddings", "canonical_id", nullable=False)

    op.drop_constraint(
        "fk_source_embeddings_tenant_source",
        "source_embeddings",
        type_="foreignkey",
    )
    op.drop_index("ix_source_embeddings_tenant_source", table_name="source_embeddings")
    op.drop_constraint(
        "uq_source_embeddings_tenant_source_model",
        "source_embeddings",
        type_="unique",
    )
    op.drop_column("source_embeddings", "source_id")

    op.create_unique_constraint(
        "uq_source_embeddings_tenant_canonical_model",
        "source_embeddings",
        ["tenant_id", "canonical_id", "embedding_model"],
    )
    op.create_index(
        "ix_source_embeddings_tenant_canonical",
        "source_embeddings",
        ["tenant_id", "canonical_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_source_embeddings_tenant_canonical", table_name="source_embeddings")
    op.drop_constraint(
        "uq_source_embeddings_tenant_canonical_model",
        "source_embeddings",
        type_="unique",
    )

    op.add_column("source_embeddings", sa.Column("source_id", sa.Uuid(as_uuid=True), nullable=True))
    op.execute(
        """
        UPDATE source_embeddings
        SET source_id = sources.id
        FROM sources
        WHERE source_embeddings.tenant_id = sources.tenant_id
          AND source_embeddings.canonical_id = sources.canonical_id
        """
    )
    op.alter_column("source_embeddings", "source_id", nullable=False)

    op.create_unique_constraint(
        "uq_source_embeddings_tenant_source_model",
        "source_embeddings",
        ["tenant_id", "source_id", "embedding_model"],
    )
    op.create_index(
        "ix_source_embeddings_tenant_source",
        "source_embeddings",
        ["tenant_id", "source_id"],
    )
    op.create_foreign_key(
        "fk_source_embeddings_tenant_source",
        "source_embeddings",
        "sources",
        ["tenant_id", "source_id"],
        ["tenant_id", "id"],
        ondelete="CASCADE",
    )

    op.drop_column("source_embeddings", "canonical_id")
