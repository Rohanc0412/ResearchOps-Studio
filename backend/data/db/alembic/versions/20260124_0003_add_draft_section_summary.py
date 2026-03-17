"""Add section summary to draft sections.

Revision ID: 20260124_0003
Revises: 20260124_0002
Create Date: 2026-01-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260124_0003"
down_revision = "20260124_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("draft_sections", sa.Column("section_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("draft_sections", "section_summary")
