"""Add outline section tables.

Revision ID: 20260123_0003
Revises: 20260123_0002
Create Date: 2026-01-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260123_0003"
down_revision = "20260123_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_sections",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("section_id", sa.String(length=100), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("section_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "section_id",
            name="uq_run_sections_tenant_run_section",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            ondelete="CASCADE",
            name="fk_run_sections_tenant_run",
        ),
    )
    op.create_index("ix_run_sections_tenant_run", "run_sections", ["tenant_id", "run_id"])
    op.create_index(
        "ix_run_sections_tenant_order",
        "run_sections",
        ["tenant_id", "run_id", "section_order"],
    )

    op.create_table(
        "outline_notes",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("section_id", sa.String(length=100), nullable=False),
        sa.Column("notes_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "section_id",
            name="uq_outline_notes_tenant_run_section",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            ondelete="CASCADE",
            name="fk_outline_notes_tenant_run",
        ),
    )
    op.create_index("ix_outline_notes_tenant_run", "outline_notes", ["tenant_id", "run_id"])


def downgrade() -> None:
    op.drop_index("ix_outline_notes_tenant_run", table_name="outline_notes")
    op.drop_table("outline_notes")

    op.drop_index("ix_run_sections_tenant_order", table_name="run_sections")
    op.drop_index("ix_run_sections_tenant_run", table_name="run_sections")
    op.drop_table("run_sections")
