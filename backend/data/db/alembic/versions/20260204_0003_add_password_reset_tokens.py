"""Add password reset tokens table.

Revision ID: 20260204_0003
Revises: 20260204_0002
Create Date: 2026-02-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260204_0003"
down_revision = "20260204_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_password_resets",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_auth_password_resets_hash"),
    )
    op.create_index("ix_auth_password_resets_expires_at", "auth_password_resets", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_auth_password_resets_expires_at", table_name="auth_password_resets")
    op.drop_index("ix_auth_password_resets_tenant_id", table_name="auth_password_resets")
    op.drop_index("ix_auth_password_resets_user_id", table_name="auth_password_resets")
    op.drop_table("auth_password_resets")
