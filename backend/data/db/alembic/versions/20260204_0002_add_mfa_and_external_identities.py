"""Add MFA factors and external identities.

Revision ID: 20260204_0002
Revises: 20260202_0001
Create Date: 2026-02-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260204_0002"
down_revision = "20260202_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("auth_external_identities"):
        op.create_table(
            "auth_external_identities",
            sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
            sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("provider_user_id", sa.String(length=200), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "provider", "provider_user_id", name="uq_auth_external_identities_provider_user"
            ),
        )

    if not inspector.has_table("auth_mfa_factors"):
        op.create_table(
            "auth_mfa_factors",
            sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
            sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
            sa.Column("factor_type", sa.String(length=20), nullable=False, server_default="totp"),
            sa.Column("secret", sa.String(length=128), nullable=False),
            sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("user_id", "factor_type", name="uq_auth_mfa_factors_user_type"),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_auth_external_identities_provider "
        "ON auth_external_identities (provider)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_auth_mfa_factors_enabled_at "
        "ON auth_mfa_factors (enabled_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_auth_mfa_factors_enabled_at")
    op.execute("DROP TABLE IF EXISTS auth_mfa_factors")

    op.execute("DROP INDEX IF EXISTS ix_auth_external_identities_provider")
    op.execute("DROP TABLE IF EXISTS auth_external_identities")
