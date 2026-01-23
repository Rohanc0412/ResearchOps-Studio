"""Add retrieval tables and source metadata columns.

Revision ID: 20260122_0001
Revises: 20260121_0001
Create Date: 2026-01-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260122_0001"
down_revision = "20260121_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("venue", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("doi", sa.String(length=128), nullable=True))
    op.add_column("sources", sa.Column("arxiv_id", sa.String(length=64), nullable=True))
    op.add_column("sources", sa.Column("origin", sa.String(length=50), nullable=True))
    op.add_column("sources", sa.Column("cited_by_count", sa.Integer(), nullable=True))
    op.create_index("ix_sources_tenant_doi", "sources", ["tenant_id", "doi"])
    op.create_index("ix_sources_tenant_arxiv", "sources", ["tenant_id", "arxiv_id"])

    op.create_table(
        "run_sources",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("origin", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "source_id",
            name="uq_run_sources_tenant_run_source",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            ondelete="CASCADE",
            name="fk_run_sources_tenant_run",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_id"],
            ["sources.tenant_id", "sources.id"],
            ondelete="CASCADE",
            name="fk_run_sources_tenant_source",
        ),
    )
    op.create_index("ix_run_sources_tenant_run", "run_sources", ["tenant_id", "run_id"])
    op.create_index("ix_run_sources_tenant_source", "run_sources", ["tenant_id", "source_id"])

    op.create_table(
        "run_checkpoints",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("stage", sa.String(length=100), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            ondelete="CASCADE",
            name="fk_run_checkpoints_tenant_run",
        ),
    )
    op.create_index("ix_run_checkpoints_tenant_run", "run_checkpoints", ["tenant_id", "run_id"])
    op.create_index("ix_run_checkpoints_tenant_stage", "run_checkpoints", ["tenant_id", "stage"])


def downgrade() -> None:
    op.drop_index("ix_run_checkpoints_tenant_stage", table_name="run_checkpoints")
    op.drop_index("ix_run_checkpoints_tenant_run", table_name="run_checkpoints")
    op.drop_table("run_checkpoints")

    op.drop_index("ix_run_sources_tenant_source", table_name="run_sources")
    op.drop_index("ix_run_sources_tenant_run", table_name="run_sources")
    op.drop_table("run_sources")

    op.drop_index("ix_sources_tenant_arxiv", table_name="sources")
    op.drop_index("ix_sources_tenant_doi", table_name="sources")
    op.drop_column("sources", "cited_by_count")
    op.drop_column("sources", "origin")
    op.drop_column("sources", "arxiv_id")
    op.drop_column("sources", "doi")
    op.drop_column("sources", "venue")
