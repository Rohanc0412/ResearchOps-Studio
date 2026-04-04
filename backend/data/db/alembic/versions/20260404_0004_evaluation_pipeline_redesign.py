"""Evaluation pipeline redesign: add section_claims, update eval tables, drop retired tables."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260404_0004_eval_redesign"
down_revision = "20260402_0003_evt_checkpoint"
branch_labels = None
depends_on = None


def _table_exists(bind: sa.engine.Connection, table_name: str) -> bool:
    return sa.inspect(bind).has_table(table_name)


def _column_names(bind: sa.engine.Connection, table_name: str) -> set[str]:
    return {col["name"] for col in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Create section_claims table
    if not _table_exists(bind, "section_claims"):
        op.create_table(
            "section_claims",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("section_id", sa.String(100), nullable=False),
            sa.Column("claim_index", sa.Integer(), nullable=False),
            sa.Column("claim_text", sa.Text(), nullable=False),
            sa.Column(
                "extracted_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_unique_constraint(
            "uq_section_claims_position",
            "section_claims",
            ["tenant_id", "run_id", "section_id", "claim_index"],
        )
        op.create_index(
            "ix_section_claims_lookup",
            "section_claims",
            ["tenant_id", "run_id", "section_id"],
        )

    # 2. Update evaluation_passes: add quality_pct + hallucination_rate, drop old columns
    ep_cols = _column_names(bind, "evaluation_passes")
    if "quality_pct" not in ep_cols:
        op.add_column("evaluation_passes", sa.Column("quality_pct", sa.Integer(), nullable=True))
    if "hallucination_rate" not in ep_cols:
        op.add_column("evaluation_passes", sa.Column("hallucination_rate", sa.Integer(), nullable=True))
    for old_col in ("grounding_pct", "faithfulness_pct", "sections_passed", "sections_total"):
        if old_col in ep_cols:
            op.drop_column("evaluation_passes", old_col)

    # 3. Update evaluation_pass_sections: add quality_score + claims_json, drop old columns
    eps_cols = _column_names(bind, "evaluation_pass_sections")
    if "quality_score" not in eps_cols:
        op.add_column("evaluation_pass_sections", sa.Column("quality_score", sa.Integer(), nullable=True))
    if "claims_json" not in eps_cols:
        op.add_column(
            "evaluation_pass_sections",
            sa.Column(
                "claims_json",
                postgresql.JSONB(),
                nullable=False,
                server_default="[]",
            ),
        )
    for old_col in ("verdict", "grounding_score", "issues_json"):
        if old_col in eps_cols:
            op.drop_column("evaluation_pass_sections", old_col)

    # 4. Drop retired tables (children first to respect FK constraints)
    for table in ("section_review_issue_citations", "section_review_issues", "section_reviews"):
        if _table_exists(bind, table):
            op.drop_table(table)


def downgrade() -> None:
    bind = op.get_bind()

    # Restore evaluation_pass_sections columns
    eps_cols = _column_names(bind, "evaluation_pass_sections")
    for col, type_ in [
        ("verdict", sa.String(10)),
        ("grounding_score", sa.Integer()),
        ("issues_json", postgresql.JSONB()),
    ]:
        if col not in eps_cols:
            op.add_column("evaluation_pass_sections", sa.Column(col, type_, nullable=True))
    for col in ("quality_score", "claims_json"):
        if col in eps_cols:
            op.drop_column("evaluation_pass_sections", col)

    # Restore evaluation_passes columns
    ep_cols = _column_names(bind, "evaluation_passes")
    for col, type_ in [
        ("grounding_pct", sa.Integer()),
        ("faithfulness_pct", sa.Integer()),
        ("sections_passed", sa.Integer()),
        ("sections_total", sa.Integer()),
    ]:
        if col not in ep_cols:
            op.add_column("evaluation_passes", sa.Column(col, type_, nullable=True))
    for col in ("quality_pct", "hallucination_rate"):
        if col in ep_cols:
            op.drop_column("evaluation_passes", col)

    # Drop section_claims
    if _table_exists(bind, "section_claims"):
        op.drop_table("section_claims")
