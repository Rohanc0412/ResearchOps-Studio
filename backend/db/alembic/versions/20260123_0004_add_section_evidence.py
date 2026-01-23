"""Add section evidence mapping table.

Revision ID: 20260123_0004
Revises: 20260123_0003
Create Date: 2026-01-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260123_0004"
down_revision = "20260123_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "section_evidence",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("section_id", sa.String(length=100), nullable=False),
        sa.Column("snippet_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "section_id",
            "snippet_id",
            name="uq_section_evidence_tenant_run_section_snippet",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            ondelete="CASCADE",
            name="fk_section_evidence_tenant_run",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "snippet_id"],
            ["snippets.tenant_id", "snippets.id"],
            ondelete="CASCADE",
            name="fk_section_evidence_tenant_snippet",
        ),
    )
    op.create_index(
        "ix_section_evidence_tenant_section",
        "section_evidence",
        ["tenant_id", "run_id", "section_id"],
    )
    op.create_index(
        "ix_section_evidence_tenant_snippet",
        "section_evidence",
        ["tenant_id", "snippet_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_section_evidence_tenant_snippet", table_name="section_evidence")
    op.drop_index("ix_section_evidence_tenant_section", table_name="section_evidence")
    op.drop_table("section_evidence")
