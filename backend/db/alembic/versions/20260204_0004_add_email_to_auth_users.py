"""Add email to auth users.

Revision ID: 20260204_0004
Revises: 20260204_0003
Create Date: 2026-02-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260204_0004"
down_revision = "20260204_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auth_users", sa.Column("email", sa.String(length=200), nullable=True))
    op.create_unique_constraint("uq_auth_users_email", "auth_users", ["email"])
    op.execute("UPDATE auth_users SET email = username")
    op.alter_column("auth_users", "email", nullable=False)


def downgrade() -> None:
    op.drop_constraint("uq_auth_users_email", "auth_users", type_="unique")
    op.drop_column("auth_users", "email")
