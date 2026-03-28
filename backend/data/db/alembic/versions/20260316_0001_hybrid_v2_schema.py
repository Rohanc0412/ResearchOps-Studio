"""Hybrid v2 normalized schema baseline."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

import db.models  # noqa: F401
from db.models.base import Base


revision = "20260316_0001_hybrid_v2"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind)
