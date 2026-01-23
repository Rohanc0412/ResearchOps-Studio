"""Add source embeddings cache table.

Revision ID: 20260123_0001
Revises: 20260122_0001
Create Date: 2026-01-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260123_0001"
down_revision = "20260122_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_embeddings",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("embedding_dim", sa.Integer(), nullable=False),
        sa.Column("embedding_json", sa.JSON(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "source_id",
            "embedding_model",
            name="uq_source_embeddings_tenant_source_model",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_source_embeddings_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_id"],
            ["sources.tenant_id", "sources.id"],
            ondelete="CASCADE",
            name="fk_source_embeddings_tenant_source",
        ),
    )
    op.create_index("ix_source_embeddings_tenant_model", "source_embeddings", ["tenant_id", "embedding_model"])
    op.create_index("ix_source_embeddings_tenant_source", "source_embeddings", ["tenant_id", "source_id"])


def downgrade() -> None:
    op.drop_index("ix_source_embeddings_tenant_source", table_name="source_embeddings")
    op.drop_index("ix_source_embeddings_tenant_model", table_name="source_embeddings")
    op.drop_table("source_embeddings")
