"""Add run lifecycle fields (cancel_requested_at, retry_count, blocked state).

Revision ID: 20260117_0001
Revises: 20260116_0001
Create Date: 2026-01-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260117_0001"
down_revision = "20260116_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add 'blocked' to run_status enum if using PostgreSQL
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == "postgresql":
        # Add new enum value to run_status
        op.execute("ALTER TYPE run_status ADD VALUE IF NOT EXISTS 'blocked'")
        op.execute("ALTER TYPE project_last_run_status ADD VALUE IF NOT EXISTS 'blocked'")

    # Add new columns to runs table
    op.add_column("runs", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("runs", sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False))

    # Create index for cancel_requested_at to optimize cancellation queries
    op.create_index(
        "ix_runs_tenant_cancel_requested",
        "runs",
        ["tenant_id", "cancel_requested_at"],
        postgresql_where=sa.text("cancel_requested_at IS NOT NULL"),
    )

    # Add sequential event_number to run_events for SSE Last-Event-ID support
    # Use BigInteger for large event counts
    op.add_column("run_events", sa.Column("event_number", sa.BigInteger(), nullable=True))

    # Create sequence for event_number
    if dialect_name == "postgresql":
        op.execute("CREATE SEQUENCE IF NOT EXISTS run_events_event_number_seq")
        # Backfill existing events with sequential numbers based on ts ordering
        op.execute("""
            UPDATE run_events
            SET event_number = subq.rn
            FROM (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY tenant_id, run_id ORDER BY ts, id) as rn
                FROM run_events
            ) subq
            WHERE run_events.id = subq.id
        """)
        # Set the sequence to start after the max event_number.
        # If there are no rows yet, setval(..., 1, false) so the first nextval() returns 1.
        op.execute(
            """
            SELECT setval(
                'run_events_event_number_seq',
                COALESCE((SELECT MAX(event_number) FROM run_events), 1),
                (SELECT MAX(event_number) FROM run_events) IS NOT NULL
            )
            """
        )
        # Set default for future inserts
        op.execute("ALTER TABLE run_events ALTER COLUMN event_number SET DEFAULT nextval('run_events_event_number_seq')")
    else:
        # For SQLite, use autoincrement
        # Backfill with row numbers
        op.execute("""
            UPDATE run_events
            SET event_number = (
                SELECT COUNT(*)
                FROM run_events e2
                WHERE e2.tenant_id = run_events.tenant_id
                AND e2.run_id = run_events.run_id
                AND (e2.ts < run_events.ts OR (e2.ts = run_events.ts AND e2.id <= run_events.id))
            )
        """)

    # Make event_number NOT NULL after backfill
    op.alter_column("run_events", "event_number", nullable=False)

    # Create index for efficient SSE queries (after_event_number lookups)
    op.create_index(
        "ix_run_events_tenant_run_event_number",
        "run_events",
        ["tenant_id", "run_id", "event_number"],
    )

    # Add event_type column to run_events for structured event categorization
    op.add_column("run_events", sa.Column("event_type", sa.String(length=100), nullable=True))

    # Backfill existing events with event_type="log" as default
    op.execute("UPDATE run_events SET event_type = 'log' WHERE event_type IS NULL")

    # Make event_type NOT NULL
    op.alter_column("run_events", "event_type", nullable=False, server_default="log")


def downgrade() -> None:
    # Drop run_events changes
    op.drop_index("ix_run_events_tenant_run_event_number", table_name="run_events")
    op.drop_column("run_events", "event_type")
    op.drop_column("run_events", "event_number")

    bind = op.get_bind()
    dialect_name = bind.dialect.name
    if dialect_name == "postgresql":
        op.execute("DROP SEQUENCE IF EXISTS run_events_event_number_seq")

    # Drop runs table changes
    op.drop_index("ix_runs_tenant_cancel_requested", table_name="runs")
    op.drop_column("runs", "retry_count")
    op.drop_column("runs", "cancel_requested_at")
    # Note: PostgreSQL enum values cannot be removed easily, so we leave 'blocked' in the enum
