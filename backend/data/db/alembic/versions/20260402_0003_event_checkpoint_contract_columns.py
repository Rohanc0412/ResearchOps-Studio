"""Add event/checkpoint contract columns for orchestrator runtime."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260402_0003_evt_checkpoint"
down_revision = "20260330_0002_evaluation_history"
branch_labels = None
depends_on = None


def _column_names(bind: sa.engine.Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(bind: sa.engine.Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()

    run_event_audience = sa.Enum(
        "progress",
        "diagnostic",
        "state",
        name="run_event_audience",
    )
    run_event_audience.create(bind, checkfirst=True)

    run_event_columns = _column_names(bind, "run_events")
    if "audience" not in run_event_columns:
        op.add_column(
            "run_events",
            sa.Column(
                "audience",
                run_event_audience,
                nullable=False,
                server_default=sa.text("'diagnostic'"),
            ),
        )

    run_checkpoint_columns = _column_names(bind, "run_checkpoints")
    if "checkpoint_version" not in run_checkpoint_columns:
        op.add_column(
            "run_checkpoints",
            sa.Column(
                "checkpoint_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
        )
    if "node_name" not in run_checkpoint_columns:
        op.add_column(
            "run_checkpoints",
            sa.Column(
                "node_name",
                sa.String(length=100),
                nullable=False,
                server_default=sa.text("'unknown'"),
            ),
        )
    if "iteration_count" not in run_checkpoint_columns:
        op.add_column(
            "run_checkpoints",
            sa.Column(
                "iteration_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    if "summary_json" not in run_checkpoint_columns:
        op.add_column(
            "run_checkpoints",
            sa.Column(
                "summary_json",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )

    checkpoint_indexes = _index_names(bind, "run_checkpoints")
    if "ix_run_checkpoints_tenant_node_name" not in checkpoint_indexes:
        op.create_index(
            "ix_run_checkpoints_tenant_node_name",
            "run_checkpoints",
            ["tenant_id", "node_name"],
            unique=False,
        )
    if "ix_run_checkpoints_node_name" in checkpoint_indexes:
        op.drop_index("ix_run_checkpoints_node_name", table_name="run_checkpoints")


def downgrade() -> None:
    bind = op.get_bind()

    checkpoint_indexes = _index_names(bind, "run_checkpoints")
    if "ix_run_checkpoints_tenant_node_name" in checkpoint_indexes:
        op.drop_index("ix_run_checkpoints_tenant_node_name", table_name="run_checkpoints")

    run_checkpoint_columns = _column_names(bind, "run_checkpoints")
    if "summary_json" in run_checkpoint_columns:
        op.drop_column("run_checkpoints", "summary_json")
    if "iteration_count" in run_checkpoint_columns:
        op.drop_column("run_checkpoints", "iteration_count")
    if "node_name" in run_checkpoint_columns:
        op.drop_column("run_checkpoints", "node_name")
    if "checkpoint_version" in run_checkpoint_columns:
        op.drop_column("run_checkpoints", "checkpoint_version")

    run_event_columns = _column_names(bind, "run_events")
    if "audience" in run_event_columns:
        op.drop_column("run_events", "audience")

    run_event_audience = sa.Enum(
        "progress",
        "diagnostic",
        "state",
        name="run_event_audience",
    )
    run_event_audience.drop(bind, checkfirst=True)
