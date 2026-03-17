"""Part 4 truth-storage schema (projects/runs/evidence/artifacts/claims).

Revision ID: 20260116_0001
Revises: None
Create Date: 2026-01-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector


revision = "20260116_0001"
down_revision = None
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    bind = op.get_bind()
    project_last_run_status_enum = postgresql.ENUM(
        "created",
        "queued",
        "running",
        "failed",
        "succeeded",
        "canceled",
        name="project_last_run_status",
        create_type=False,
    )
    run_status_enum = postgresql.ENUM(
        "created",
        "queued",
        "running",
        "failed",
        "succeeded",
        "canceled",
        name="run_status",
        create_type=False,
    )
    run_event_level_enum = postgresql.ENUM(
        "debug",
        "info",
        "warn",
        "error",
        name="run_event_level",
        create_type=False,
    )
    claim_verdict_enum = postgresql.ENUM(
        "supported",
        "unsupported",
        "partially_supported",
        "needs_citation",
        name="claim_verdict",
        create_type=False,
    )
    job_status_enum = postgresql.ENUM(
        "queued",
        "running",
        "failed",
        "succeeded",
        name="job_status",
        create_type=False,
    )

    project_last_run_status_enum.create(bind, checkfirst=True)
    run_status_enum.create(bind, checkfirst=True)
    run_event_level_enum.create(bind, checkfirst=True)
    claim_verdict_enum.create(bind, checkfirst=True)
    job_status_enum.create(bind, checkfirst=True)

    if not _has_table("audit_logs"):
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("actor_user_id", sa.String(length=200), nullable=False),
            sa.Column("action", sa.String(length=200), nullable=False),
            sa.Column("target_type", sa.String(length=100), nullable=False),
            sa.Column("target_id", sa.String(length=200), nullable=True),
            sa.Column("metadata", postgresql.JSONB(), nullable=False),
            sa.Column("ip", sa.String(length=100), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("request_id", sa.String(length=100), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint("tenant_id", "id", name="uq_audit_logs_tenant_id_id"),
        )
        op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
        op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
        op.create_index(
            "ix_audit_logs_tenant_created_at", "audit_logs", ["tenant_id", "created_at"]
        )
        op.create_index("ix_audit_logs_tenant_action", "audit_logs", ["tenant_id", "action"])

    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_run_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "last_run_status",
            project_last_run_status_enum,
            nullable=True,
        ),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "name", name="uq_projects_tenant_name"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_projects_tenant_id_id"),
    )
    op.create_index("ix_projects_tenant_id", "projects", ["tenant_id"])
    op.create_index("ix_projects_created_at", "projects", ["created_at"])
    op.create_index("ix_projects_tenant_created_at", "projects", ["tenant_id", "created_at"])
    op.create_index(
        "ix_projects_tenant_last_activity_at_desc",
        "projects",
        ["tenant_id", sa.text("last_activity_at DESC")],
    )
    op.create_index("ix_projects_tenant_name", "projects", ["tenant_id", "name"])

    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            run_status_enum,
            nullable=False,
        ),
        sa.Column("current_stage", sa.String(length=200), nullable=True),
        sa.Column(
            "budgets_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "usage_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_runs_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="CASCADE",
            name="fk_runs_tenant_project",
        ),
    )
    op.create_index("ix_runs_tenant_id", "runs", ["tenant_id"])
    op.create_index("ix_runs_project_id", "runs", ["project_id"])
    op.create_index("ix_runs_created_at", "runs", ["created_at"])
    op.create_index("ix_runs_updated_at", "runs", ["updated_at"])
    op.create_index(
        "ix_runs_tenant_project_created_at_desc",
        "runs",
        ["tenant_id", "project_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_runs_tenant_status_created_at_desc",
        "runs",
        ["tenant_id", "status", sa.text("created_at DESC")],
    )
    op.create_index("ix_runs_tenant_id_id", "runs", ["tenant_id", "id"])

    op.create_foreign_key(
        "fk_projects_last_run",
        "projects",
        "runs",
        ["tenant_id", "last_run_id"],
        ["tenant_id", "id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "run_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("stage", sa.String(length=200), nullable=True),
        sa.Column(
            "level",
            run_event_level_enum,
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_run_events_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            ondelete="CASCADE",
            name="fk_run_events_tenant_run",
        ),
    )
    op.create_index("ix_run_events_tenant_id", "run_events", ["tenant_id"])
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])
    op.create_index(
        "ix_run_events_tenant_run_ts_asc",
        "run_events",
        ["tenant_id", "run_id", sa.text("ts ASC")],
    )
    op.create_index(
        "ix_run_events_tenant_run_stage_ts_asc",
        "run_events",
        ["tenant_id", "run_id", "stage", sa.text("ts ASC")],
    )

    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("canonical_id", sa.String(length=500), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "authors_json",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "canonical_id", name="uq_sources_tenant_canonical"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_sources_tenant_id_id"),
    )
    op.create_index("ix_sources_tenant_id", "sources", ["tenant_id"])
    op.create_index("ix_sources_created_at", "sources", ["created_at"])
    op.create_index("ix_sources_updated_at", "sources", ["updated_at"])
    op.create_index(
        "ix_sources_tenant_type_year_desc", "sources", ["tenant_id", "source_type", "year"]
    )

    op.create_table(
        "snapshots",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column(
            "retrieved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("content_type", sa.String(length=50), nullable=True),
        sa.Column("blob_ref", sa.String(length=1000), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "source_id", "snapshot_version", name="uq_snapshots_tenant_source_version"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_snapshots_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_id"],
            ["sources.tenant_id", "sources.id"],
            ondelete="CASCADE",
            name="fk_snapshots_tenant_source",
        ),
    )
    op.create_index("ix_snapshots_tenant_id", "snapshots", ["tenant_id"])
    op.create_index("ix_snapshots_source_id", "snapshots", ["source_id"])
    op.create_index("ix_snapshots_retrieved_at", "snapshots", ["retrieved_at"])
    op.create_index("ix_snapshots_sha256", "snapshots", ["sha256"])
    op.create_index(
        "ix_snapshots_tenant_source_version_desc",
        "snapshots",
        ["tenant_id", "source_id", sa.text("snapshot_version DESC")],
    )
    op.create_index(
        "ix_snapshots_tenant_source_retrieved_at_desc",
        "snapshots",
        ["tenant_id", "source_id", sa.text("retrieved_at DESC")],
    )

    op.create_table(
        "snippets",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("snippet_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "risk_flags_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "tenant_id", "snapshot_id", "snippet_index", name="uq_snippets_tenant_snapshot_index"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_snippets_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "snapshot_id"],
            ["snapshots.tenant_id", "snapshots.id"],
            ondelete="CASCADE",
            name="fk_snippets_tenant_snapshot",
        ),
    )
    op.create_index("ix_snippets_tenant_id", "snippets", ["tenant_id"])
    op.create_index("ix_snippets_snapshot_id", "snippets", ["snapshot_id"])
    op.create_index("ix_snippets_created_at", "snippets", ["created_at"])
    op.create_index(
        "ix_snippets_tenant_snapshot_index",
        "snippets",
        ["tenant_id", "snapshot_id", "snippet_index"],
    )
    op.create_index("ix_snippets_tenant_snapshot", "snippets", ["tenant_id", "snapshot_id"])
    op.create_index("ix_snippets_tenant_sha256", "snippets", ["tenant_id", "sha256"])

    op.create_table(
        "snippet_embeddings",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("snippet_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("dims", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "snippet_id",
            "embedding_model",
            name="uq_snippet_embeddings_tenant_snippet_model",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_snippet_embeddings_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "snippet_id"],
            ["snippets.tenant_id", "snippets.id"],
            ondelete="CASCADE",
            name="fk_snippet_embeddings_tenant_snippet",
        ),
    )
    op.create_index("ix_snippet_embeddings_tenant_id", "snippet_embeddings", ["tenant_id"])
    op.create_index("ix_snippet_embeddings_snippet_id", "snippet_embeddings", ["snippet_id"])
    op.create_index(
        "ix_snippet_embeddings_tenant_snippet",
        "snippet_embeddings",
        ["tenant_id", "snippet_id"],
    )
    op.create_index(
        "ix_snippet_embeddings_embedding_ivfflat",
        "snippet_embeddings",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"lists": 100},
    )

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("blob_ref", sa.String(length=1000), nullable=False),
        sa.Column("mime_type", sa.String(length=200), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_artifacts_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="CASCADE",
            name="fk_artifacts_tenant_project",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            ondelete="SET NULL",
            name="fk_artifacts_tenant_run",
        ),
    )
    op.create_index("ix_artifacts_tenant_id", "artifacts", ["tenant_id"])
    op.create_index("ix_artifacts_project_id", "artifacts", ["project_id"])
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])
    op.create_index("ix_artifacts_created_at", "artifacts", ["created_at"])
    op.create_index(
        "ix_artifacts_tenant_project_created_at_desc",
        "artifacts",
        ["tenant_id", "project_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_artifacts_tenant_run_created_at_desc",
        "artifacts",
        ["tenant_id", "run_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_artifacts_tenant_type_created_at_desc",
        "artifacts",
        ["tenant_id", "type", sa.text("created_at DESC")],
    )

    op.create_table(
        "claim_map",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("claim_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "snippet_ids_json",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "verdict",
            claim_verdict_enum,
            nullable=False,
        ),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_claim_map_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="CASCADE",
            name="fk_claim_map_tenant_project",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            ondelete="CASCADE",
            name="fk_claim_map_tenant_run",
        ),
    )
    op.create_index("ix_claim_map_tenant_id", "claim_map", ["tenant_id"])
    op.create_index("ix_claim_map_project_id", "claim_map", ["project_id"])
    op.create_index("ix_claim_map_run_id", "claim_map", ["run_id"])
    op.create_index("ix_claim_map_created_at", "claim_map", ["created_at"])
    op.create_index(
        "ix_claim_map_tenant_run_created_at_desc",
        "claim_map",
        ["tenant_id", "run_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_claim_map_tenant_project_created_at_desc",
        "claim_map",
        ["tenant_id", "project_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_claim_map_tenant_claim_hash", "claim_map", ["tenant_id", "claim_hash"])

    if not _has_table("jobs"):
        op.create_table(
            "jobs",
            sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("job_type", sa.String(length=100), nullable=False),
            sa.Column(
                "status",
                job_status_enum,
                nullable=False,
            ),
            sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint("tenant_id", "id", name="uq_jobs_tenant_id_id"),
            sa.ForeignKeyConstraint(
                ["tenant_id", "run_id"],
                ["runs.tenant_id", "runs.id"],
                ondelete="CASCADE",
                name="fk_jobs_tenant_run",
            ),
        )
        op.create_index("ix_jobs_tenant_id", "jobs", ["tenant_id"])
        op.create_index("ix_jobs_run_id", "jobs", ["run_id"])
        op.create_index("ix_jobs_tenant_run", "jobs", ["tenant_id", "run_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_tenant_run", table_name="jobs")
    op.drop_index("ix_jobs_run_id", table_name="jobs")
    op.drop_index("ix_jobs_tenant_id", table_name="jobs")
    op.drop_table("jobs")

    op.drop_index("ix_claim_map_tenant_claim_hash", table_name="claim_map")
    op.drop_index("ix_claim_map_tenant_project_created_at_desc", table_name="claim_map")
    op.drop_index("ix_claim_map_tenant_run_created_at_desc", table_name="claim_map")
    op.drop_index("ix_claim_map_created_at", table_name="claim_map")
    op.drop_index("ix_claim_map_run_id", table_name="claim_map")
    op.drop_index("ix_claim_map_project_id", table_name="claim_map")
    op.drop_index("ix_claim_map_tenant_id", table_name="claim_map")
    op.drop_table("claim_map")

    op.drop_index("ix_artifacts_tenant_type_created_at_desc", table_name="artifacts")
    op.drop_index("ix_artifacts_tenant_run_created_at_desc", table_name="artifacts")
    op.drop_index("ix_artifacts_tenant_project_created_at_desc", table_name="artifacts")
    op.drop_index("ix_artifacts_created_at", table_name="artifacts")
    op.drop_index("ix_artifacts_run_id", table_name="artifacts")
    op.drop_index("ix_artifacts_project_id", table_name="artifacts")
    op.drop_index("ix_artifacts_tenant_id", table_name="artifacts")
    op.drop_table("artifacts")

    op.drop_index("ix_snippet_embeddings_embedding_ivfflat", table_name="snippet_embeddings")
    op.drop_index("ix_snippet_embeddings_tenant_snippet", table_name="snippet_embeddings")
    op.drop_index("ix_snippet_embeddings_snippet_id", table_name="snippet_embeddings")
    op.drop_index("ix_snippet_embeddings_tenant_id", table_name="snippet_embeddings")
    op.drop_table("snippet_embeddings")

    op.drop_index("ix_snippets_tenant_sha256", table_name="snippets")
    op.drop_index("ix_snippets_tenant_snapshot", table_name="snippets")
    op.drop_index("ix_snippets_tenant_snapshot_index", table_name="snippets")
    op.drop_index("ix_snippets_created_at", table_name="snippets")
    op.drop_index("ix_snippets_snapshot_id", table_name="snippets")
    op.drop_index("ix_snippets_tenant_id", table_name="snippets")
    op.drop_table("snippets")

    op.drop_index("ix_snapshots_tenant_source_retrieved_at_desc", table_name="snapshots")
    op.drop_index("ix_snapshots_tenant_source_version_desc", table_name="snapshots")
    op.drop_index("ix_snapshots_sha256", table_name="snapshots")
    op.drop_index("ix_snapshots_retrieved_at", table_name="snapshots")
    op.drop_index("ix_snapshots_source_id", table_name="snapshots")
    op.drop_index("ix_snapshots_tenant_id", table_name="snapshots")
    op.drop_table("snapshots")

    op.drop_index("ix_sources_tenant_type_year_desc", table_name="sources")
    op.drop_index("ix_sources_updated_at", table_name="sources")
    op.drop_index("ix_sources_created_at", table_name="sources")
    op.drop_index("ix_sources_tenant_id", table_name="sources")
    op.drop_table("sources")

    op.drop_index("ix_run_events_tenant_run_stage_ts_asc", table_name="run_events")
    op.drop_index("ix_run_events_tenant_run_ts_asc", table_name="run_events")
    op.drop_index("ix_run_events_run_id", table_name="run_events")
    op.drop_index("ix_run_events_tenant_id", table_name="run_events")
    op.drop_table("run_events")

    op.drop_constraint("fk_projects_last_run", "projects", type_="foreignkey")

    op.drop_index("ix_runs_tenant_id_id", table_name="runs")
    op.drop_index("ix_runs_tenant_status_created_at_desc", table_name="runs")
    op.drop_index("ix_runs_tenant_project_created_at_desc", table_name="runs")
    op.drop_index("ix_runs_updated_at", table_name="runs")
    op.drop_index("ix_runs_created_at", table_name="runs")
    op.drop_index("ix_runs_project_id", table_name="runs")
    op.drop_index("ix_runs_tenant_id", table_name="runs")
    op.drop_table("runs")

    op.drop_index("ix_projects_tenant_name", table_name="projects")
    op.drop_index("ix_projects_tenant_last_activity_at_desc", table_name="projects")
    op.drop_index("ix_projects_tenant_created_at", table_name="projects")
    op.drop_index("ix_projects_created_at", table_name="projects")
    op.drop_index("ix_projects_tenant_id", table_name="projects")
    op.drop_table("projects")

    op.drop_index("ix_audit_logs_tenant_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tenant_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tenant_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.execute("DROP EXTENSION IF EXISTS vector")
