"""Add draft sections table.

Revision ID: 20260124_0001
Revises: 20260123_0004
Create Date: 2026-01-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260124_0001"
down_revision = "20260123_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "draft_sections",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("section_id", sa.String(length=100), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "section_id",
            name="uq_draft_sections_tenant_run_section",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            ondelete="CASCADE",
            name="fk_draft_sections_tenant_run",
        ),
    )
    op.create_index(
        "ix_draft_sections_tenant_run",
        "draft_sections",
        ["tenant_id", "run_id"],
    )
    op.create_index(
        "ix_draft_sections_tenant_section",
        "draft_sections",
        ["tenant_id", "run_id", "section_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_draft_sections_tenant_section", table_name="draft_sections")
    op.drop_index("ix_draft_sections_tenant_run", table_name="draft_sections")
    op.drop_table("draft_sections")
