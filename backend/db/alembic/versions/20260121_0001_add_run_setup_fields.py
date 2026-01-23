"""Add run setup fields (question, output_type, client_request_id).

Revision ID: 20260121_0001
Revises: 20260120_0001
Create Date: 2026-01-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260121_0001"
down_revision = "20260120_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("question", sa.Text(), nullable=True))
    op.add_column(
        "runs",
        sa.Column("output_type", sa.String(length=50), nullable=False, server_default="report"),
    )
    op.add_column(
        "runs", sa.Column("client_request_id", sa.String(length=200), nullable=True)
    )
    op.create_index(
        "ix_runs_tenant_project_client_request_id",
        "runs",
        ["tenant_id", "project_id", "client_request_id"],
    )
    op.create_unique_constraint(
        "uq_runs_tenant_project_client_request_id",
        "runs",
        ["tenant_id", "project_id", "client_request_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_runs_tenant_project_client_request_id", "runs", type_="unique"
    )
    op.drop_index("ix_runs_tenant_project_client_request_id", table_name="runs")
    op.drop_column("runs", "client_request_id")
    op.drop_column("runs", "output_type")
    op.drop_column("runs", "question")
