"""Latest schema snapshot."""

from __future__ import annotations

import db.models  # noqa: F401
import sqlalchemy as sa
from alembic import op
from db.models.base import Base

revision = "20260330_0002_evaluation_history"
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
