"""Widen outline_notes.section_id from varchar(100) to varchar(500)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260328_0001"
down_revision = "20260316_0001_hybrid_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "outline_notes",
        "section_id",
        type_=sa.String(500),
        existing_type=sa.String(100),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "outline_notes",
        "section_id",
        type_=sa.String(100),
        existing_type=sa.String(500),
        existing_nullable=False,
    )
