"""Add section reviews table.

Revision ID: 20260124_0002
Revises: 20260124_0001
Create Date: 2026-01-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260124_0002"
down_revision = "20260124_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "section_reviews",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("section_id", sa.String(length=100), nullable=False),
        sa.Column("verdict", sa.String(length=10), nullable=False),
        sa.Column(
            "issues_json",
            sa.JSON().with_variant(postgresql.JSONB, "postgresql"),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "section_id",
            name="uq_section_reviews_tenant_run_section",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            ondelete="CASCADE",
            name="fk_section_reviews_tenant_run",
        ),
    )
    op.create_index(
        "ix_section_reviews_tenant_run",
        "section_reviews",
        ["tenant_id", "run_id"],
    )
    op.create_index(
        "ix_section_reviews_tenant_section",
        "section_reviews",
        ["tenant_id", "run_id", "section_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_section_reviews_tenant_section", table_name="section_reviews")
    op.drop_index("ix_section_reviews_tenant_run", table_name="section_reviews")
    op.drop_table("section_reviews")
