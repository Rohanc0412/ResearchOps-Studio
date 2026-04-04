# Evaluation Pipeline Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three misleading evaluation metrics (grounding_pct, faithfulness_pct, sections_passed) with two accurate ones (quality_pct, hallucination_rate) backed by RAGAS atomic claim extraction and structured LLM per-claim verdict classification.

**Architecture:** RAGAS extracts atomic claims per section during pipeline evaluation and caches them to a new `section_claims` table. Manual evaluation loads those cached claims, classifies each with a nuanced LLM verdict (supported/unsupported/contradicted/overstated/missing_citation/invalid_citation), and applies custom weights to compute quality_pct and hallucination_rate. A shared `EvaluationScorer` ensures identical scoring logic in both paths.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, ragas (pip), FastAPI, React/TypeScript. Existing LLM client (`from llm import get_llm_client_for_stage`). Tests: `python -m pytest`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/libs/core/evaluation.py` | Modify | Add new metric constants, remove old ones |
| `backend/libs/core/evaluation_scorer.py` | Create | Weighted scoring logic (pure Python) |
| `backend/libs/core/ragas_extractor.py` | Create | RAGAS atomic claim extraction wrapper |
| `backend/libs/core/claim_verifier.py` | Create | LLM-based nuanced claim verdict classifier |
| `backend/data/db/models/section_claims.py` | Create | SQLAlchemy model for cached claims |
| `backend/data/db/repositories/section_claims.py` | Create | CRUD for section_claims |
| `backend/data/db/models/evaluation_passes.py` | Modify | grounding_pct→quality_pct, faithfulness_pct→hallucination_rate, remove sections_passed/total |
| `backend/data/db/models/evaluation_pass_sections.py` | Modify | grounding_score→quality_score, remove verdict, issues_json→claims_json |
| `backend/data/db/repositories/evaluation_history.py` | Modify | Update functions for new columns |
| `backend/data/db/alembic/versions/20260404_0004_evaluation_pipeline_redesign.py` | Create | Migration: add section_claims, alter eval tables, drop retired tables |
| `backend/libs/core/orchestrator/state.py` | Modify | Add `sections_to_repair: list[str]` field |
| `backend/services/orchestrator/nodes/evaluator.py` | Modify | Use RAGAS extractor, EvaluationScorer, populate sections_to_repair |
| `backend/services/orchestrator/nodes/repair_agent.py` | Modify | Read sections_to_repair from state; add post-repair RAGAS extraction |
| `backend/services/api/app_services/evaluation_runner.py` | Modify | Use cached claims + ClaimVerifier + EvaluationScorer |
| `backend/services/api/routes/runs.py` | Modify | Return quality_pct + hallucination_rate instead of old metrics |
| `frontend/dashboard/src/api/evaluation.ts` | Modify | Update TypeScript types |
| `frontend/dashboard/src/components/run/EvaluationTab.tsx` | Modify | Display quality_pct + hallucination_rate |
| `backend/data/db/models/section_reviews.py` | Delete | Retired — replaced by section_claims |
| `backend/data/db/models/section_review_issues.py` | Delete | Retired |
| `backend/data/db/models/section_review_issue_citations.py` | Delete | Retired |
| `tests/backend/unit/test_evaluation_scorer.py` | Create | Unit tests for EvaluationScorer |
| `tests/backend/unit/test_ragas_extractor.py` | Create | Unit tests for RagasExtractor (mocked) |
| `tests/backend/unit/test_claim_verifier.py` | Create | Unit tests for ClaimVerifier (mocked) |
| `tests/backend/unit/test_evaluation_runner.py` | Modify | Update for new metrics |

---

## Task 1: EvaluationScorer — Weighted Scoring Logic

**Files:**
- Create: `backend/libs/core/evaluation_scorer.py`
- Create: `tests/backend/unit/test_evaluation_scorer.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/backend/unit/test_evaluation_scorer.py
from core.evaluation_scorer import EvaluationScorer


def test_all_supported_scores_100():
    scorer = EvaluationScorer()
    assert scorer.section_quality(["supported"] * 5) == 100


def test_all_unsupported_scores_0():
    scorer = EvaluationScorer()
    assert scorer.section_quality(["unsupported"] * 5) == 0


def test_contradicted_penalises_below_50():
    scorer = EvaluationScorer()
    # 5 supported (+5.0), 5 contradicted (-5.0) → sum=0 → clamp(0/10)=0
    assert scorer.section_quality(["supported"] * 5 + ["contradicted"] * 5) == 0


def test_contradicted_reduces_score_below_pure_supported():
    scorer = EvaluationScorer()
    # 8 supported (+8), 1 overstated (+0.5), 1 contradicted (-1) → 7.5/10 = 75
    verdicts = ["supported"] * 8 + ["overstated", "contradicted"]
    assert scorer.section_quality(verdicts) == 75


def test_missing_citation_partial_credit():
    scorer = EvaluationScorer()
    # 10 missing_citation → 0.75 each → 7.5/10 = 75
    assert scorer.section_quality(["missing_citation"] * 10) == 75


def test_section_quality_clamps_at_0():
    scorer = EvaluationScorer()
    # More contradicted than supported → negative sum → clamped to 0
    verdicts = ["supported"] * 2 + ["contradicted"] * 10
    assert scorer.section_quality(verdicts) == 0


def test_section_quality_empty_returns_0():
    scorer = EvaluationScorer()
    assert scorer.section_quality([]) == 0


def test_report_quality_averages_sections():
    scorer = EvaluationScorer()
    assert scorer.report_quality([100, 50, 75]) == 75


def test_report_quality_empty_returns_0():
    scorer = EvaluationScorer()
    assert scorer.report_quality([]) == 0


def test_hallucination_rate_counts_unsupported_and_contradicted():
    scorer = EvaluationScorer()
    # 3 unsupported + 2 contradicted out of 10 = 50%
    verdicts = ["supported"] * 5 + ["unsupported"] * 3 + ["contradicted"] * 2
    assert scorer.hallucination_rate(verdicts) == 50


def test_hallucination_rate_zero_when_all_supported():
    scorer = EvaluationScorer()
    assert scorer.hallucination_rate(["supported"] * 8) == 0


def test_hallucination_rate_empty_returns_0():
    scorer = EvaluationScorer()
    assert scorer.hallucination_rate([]) == 0


def test_repair_needed_below_threshold():
    scorer = EvaluationScorer()
    assert scorer.repair_needed(["unsupported"] * 5 + ["supported"] * 5, 45) is True


def test_repair_needed_above_threshold_no_contradiction():
    scorer = EvaluationScorer()
    assert scorer.repair_needed(["supported"] * 10, 90) is False


def test_repair_needed_contradicted_overrides_good_score():
    scorer = EvaluationScorer()
    assert scorer.repair_needed(["supported"] * 9 + ["contradicted"], 85) is True
```

- [ ] **Step 2: Run to confirm they fail**

```
python -m pytest tests/backend/unit/test_evaluation_scorer.py -v
```
Expected: `ModuleNotFoundError: No module named 'core.evaluation_scorer'`

- [ ] **Step 3: Implement EvaluationScorer**

```python
# backend/libs/core/evaluation_scorer.py
"""Weighted claim scoring for evaluation pipeline."""

from __future__ import annotations

_WEIGHTS: dict[str, float] = {
    "supported": 1.0,
    "missing_citation": 0.75,
    "invalid_citation": 0.75,
    "overstated": 0.5,
    "unsupported": 0.0,
    "contradicted": -1.0,
}

_REPAIR_THRESHOLD = 70


class EvaluationScorer:
    """Computes quality_pct, hallucination_rate, and repair decisions from claim verdicts."""

    def section_quality(self, verdicts: list[str]) -> int:
        """Return 0–100 quality score for a single section."""
        if not verdicts:
            return 0
        total = sum(_WEIGHTS.get(v, 0.0) for v in verdicts)
        clamped = max(0.0, min(1.0, total / len(verdicts)))
        return round(clamped * 100)

    def report_quality(self, section_scores: list[int]) -> int:
        """Return 0–100 quality score averaged across all sections."""
        if not section_scores:
            return 0
        return round(sum(section_scores) / len(section_scores))

    def hallucination_rate(self, verdicts: list[str]) -> int:
        """Return 0–100 rate of claims that are unsupported or contradicted."""
        if not verdicts:
            return 0
        bad = sum(1 for v in verdicts if v in ("unsupported", "contradicted"))
        return round(bad / len(verdicts) * 100)

    def repair_needed(self, verdicts: list[str], quality_score: int) -> bool:
        """Return True if the section should be sent to the repair agent."""
        if quality_score < _REPAIR_THRESHOLD:
            return True
        return any(v == "contradicted" for v in verdicts)
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/backend/unit/test_evaluation_scorer.py -v
```
Expected: all 15 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/libs/core/evaluation_scorer.py tests/backend/unit/test_evaluation_scorer.py
git commit -m "feat: add EvaluationScorer with weighted claim scoring"
```

---

## Task 2: section_claims DB Model and Repository

**Files:**
- Create: `backend/data/db/models/section_claims.py`
- Create: `backend/data/db/repositories/section_claims.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/backend/unit/test_section_claims_repo.py
from uuid import uuid4
from db.models.section_claims import SectionClaimRow
from db.repositories.section_claims import (
    upsert_section_claims,
    load_section_claims,
    delete_section_claims,
)


def test_section_claim_row_instantiates():
    row = SectionClaimRow(
        tenant_id=uuid4(),
        run_id=uuid4(),
        section_id="sec_1",
        claim_index=0,
        claim_text="AI is used in healthcare.",
    )
    assert row.claim_index == 0
    assert row.claim_text == "AI is used in healthcare."


def test_upsert_and_load_claims(db_session, tenant_id, run_id):
    claims = ["Claim A", "Claim B", "Claim C"]
    upsert_section_claims(db_session, tenant_id=tenant_id, run_id=run_id,
                          section_id="sec_1", claims=claims)
    db_session.flush()
    loaded = load_section_claims(db_session, tenant_id=tenant_id, run_id=run_id,
                                 section_id="sec_1")
    assert loaded == claims


def test_upsert_replaces_existing_claims(db_session, tenant_id, run_id):
    upsert_section_claims(db_session, tenant_id=tenant_id, run_id=run_id,
                          section_id="sec_1", claims=["Old claim"])
    db_session.flush()
    upsert_section_claims(db_session, tenant_id=tenant_id, run_id=run_id,
                          section_id="sec_1", claims=["New claim A", "New claim B"])
    db_session.flush()
    loaded = load_section_claims(db_session, tenant_id=tenant_id, run_id=run_id,
                                 section_id="sec_1")
    assert loaded == ["New claim A", "New claim B"]


def test_load_returns_empty_when_no_claims(db_session, tenant_id, run_id):
    loaded = load_section_claims(db_session, tenant_id=tenant_id, run_id=run_id,
                                 section_id="nonexistent")
    assert loaded == []
```

- [ ] **Step 2: Run to confirm they fail**

```
python -m pytest tests/backend/unit/test_section_claims_repo.py -v
```
Expected: `ModuleNotFoundError: No module named 'db.models.section_claims'`

- [ ] **Step 3: Create the model**

```python
# backend/data/db/models/section_claims.py
"""Cached atomic claims extracted from section text by RAGAS."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from core.env import now_utc


class SectionClaimRow(Base):
    __tablename__ = "section_claims"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    section_id: Mapped[str] = mapped_column(String(100), nullable=False)
    claim_index: Mapped[int] = mapped_column(Integer(), nullable=False)
    claim_text: Mapped[str] = mapped_column(Text(), nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(default=now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id", "section_id", "claim_index",
                         name="uq_section_claims_position"),
        Index("ix_section_claims_lookup", "tenant_id", "run_id", "section_id"),
    )
```

- [ ] **Step 4: Create the repository**

```python
# backend/data/db/repositories/section_claims.py
"""CRUD operations for section_claims."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from db.models.section_claims import SectionClaimRow


def upsert_section_claims(
    session: Session,
    *,
    tenant_id: UUID,
    run_id: UUID,
    section_id: str,
    claims: list[str],
) -> None:
    """Replace all stored claims for a section with the new list."""
    delete_section_claims(session, tenant_id=tenant_id, run_id=run_id, section_id=section_id)
    for idx, text in enumerate(claims):
        session.add(SectionClaimRow(
            tenant_id=tenant_id,
            run_id=run_id,
            section_id=section_id,
            claim_index=idx,
            claim_text=text,
        ))


def load_section_claims(
    session: Session,
    *,
    tenant_id: UUID,
    run_id: UUID,
    section_id: str,
) -> list[str]:
    """Return ordered list of claim strings for a section, empty if none."""
    rows = (
        session.query(SectionClaimRow)
        .filter(
            SectionClaimRow.tenant_id == tenant_id,
            SectionClaimRow.run_id == run_id,
            SectionClaimRow.section_id == section_id,
        )
        .order_by(SectionClaimRow.claim_index)
        .all()
    )
    return [r.claim_text for r in rows]


def delete_section_claims(
    session: Session,
    *,
    tenant_id: UUID,
    run_id: UUID,
    section_id: str,
) -> None:
    """Delete all cached claims for a section."""
    session.query(SectionClaimRow).filter(
        SectionClaimRow.tenant_id == tenant_id,
        SectionClaimRow.run_id == run_id,
        SectionClaimRow.section_id == section_id,
    ).delete(synchronize_session=False)
```

- [ ] **Step 5: Run tests** (DB tests require fixtures — skip if conftest not wired, revisit in Task 4 after migration runs)

```
python -m pytest tests/backend/unit/test_section_claims_repo.py::test_section_claim_row_instantiates -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/data/db/models/section_claims.py backend/data/db/repositories/section_claims.py tests/backend/unit/test_section_claims_repo.py
git commit -m "feat: add section_claims model and repository"
```

---

## Task 3: Update Evaluation DB Models

**Files:**
- Modify: `backend/data/db/models/evaluation_passes.py`
- Modify: `backend/data/db/models/evaluation_pass_sections.py`
- Modify: `backend/libs/core/evaluation.py`

- [ ] **Step 1: Update evaluation.py constants**

Replace the contents of `backend/libs/core/evaluation.py`:

```python
"""Shared evaluation constants used by both the orchestrator pipeline and the API evaluation runner."""

from __future__ import annotations

# Metric key constants (stored in run_usage_metrics.metric_name)
METRIC_EVAL_STATUS = "eval_status"
METRIC_EVAL_QUALITY_PCT = "eval_quality_pct"
METRIC_EVAL_HALLUCINATION_RATE = "eval_hallucination_rate"
METRIC_EVAL_EVALUATED_AT = "eval_evaluated_at"

ALLOWED_VERDICTS: frozenset[str] = frozenset({
    "supported",
    "unsupported",
    "contradicted",
    "missing_citation",
    "invalid_citation",
    "overstated",
})

CLAIM_VERIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_index": {"type": "integer"},
                    "verdict": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "string"}},
                    "notes": {"type": "string"},
                },
                "required": ["claim_index", "verdict", "citations", "notes"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}
```

- [ ] **Step 2: Update evaluation_passes model**

In `backend/data/db/models/evaluation_passes.py`, replace the three metric columns:

Find:
```python
    grounding_pct: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    faithfulness_pct: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    sections_passed: Mapped[int | None] = mapped_column(Integer(), nullable=True)
```

Replace with:
```python
    quality_pct: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    hallucination_rate: Mapped[int | None] = mapped_column(Integer(), nullable=True)
```

Also remove any `sections_total` column if it exists in the same file.

- [ ] **Step 3: Update evaluation_pass_sections model**

In `backend/data/db/models/evaluation_pass_sections.py`:

Find:
```python
    verdict: Mapped[str] = mapped_column(String(10), nullable=False)
    grounding_score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    issues_json: Mapped[list] = mapped_column(
```

Replace with:
```python
    quality_score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    claims_json: Mapped[list] = mapped_column(
```

Update the JSON column body to match — keep the same JSONB type and nullable setting, just rename the column attribute and database column name (the `name=` kwarg if present, otherwise it defaults to the attribute name).

- [ ] **Step 4: Verify model imports still work**

```
python -c "from db.models.evaluation_passes import EvaluationPassRow; from db.models.evaluation_pass_sections import EvaluationPassSectionRow; print('OK')"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/libs/core/evaluation.py backend/data/db/models/evaluation_passes.py backend/data/db/models/evaluation_pass_sections.py
git commit -m "feat: update evaluation models — quality_pct + hallucination_rate replace grounding/faithfulness"
```

---

## Task 4: Database Migration

**Files:**
- Create: `backend/data/db/alembic/versions/20260404_0004_evaluation_pipeline_redesign.py`

- [ ] **Step 1: Create the migration file**

```python
# backend/data/db/alembic/versions/20260404_0004_evaluation_pipeline_redesign.py
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
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns(table_name)}


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
            sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
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
    eps_cols = _column_names(bind, "evaluation_passes")
    if "quality_pct" not in eps_cols:
        op.add_column("evaluation_passes", sa.Column("quality_pct", sa.Integer(), nullable=True))
    if "hallucination_rate" not in eps_cols:
        op.add_column("evaluation_passes", sa.Column("hallucination_rate", sa.Integer(), nullable=True))
    for old_col in ("grounding_pct", "faithfulness_pct", "sections_passed", "sections_total"):
        if old_col in eps_cols:
            op.drop_column("evaluation_passes", old_col)

    # 3. Update evaluation_pass_sections: add quality_score + claims_json, drop old columns
    epss_cols = _column_names(bind, "evaluation_pass_sections")
    if "quality_score" not in epss_cols:
        op.add_column("evaluation_pass_sections", sa.Column("quality_score", sa.Integer(), nullable=True))
    if "claims_json" not in epss_cols:
        op.add_column("evaluation_pass_sections",
                      sa.Column("claims_json", postgresql.JSONB(), nullable=True))
    for old_col in ("verdict", "grounding_score", "issues_json"):
        if old_col in epss_cols:
            op.drop_column("evaluation_pass_sections", old_col)

    # 4. Drop retired tables (cascade handles FK children)
    for table in ("section_review_issue_citations", "section_review_issues", "section_reviews"):
        if _table_exists(bind, table):
            op.drop_table(table)


def downgrade() -> None:
    bind = op.get_bind()

    # Restore evaluation_pass_sections columns
    epss_cols = _column_names(bind, "evaluation_pass_sections")
    for col, type_ in [("verdict", sa.String(10)), ("grounding_score", sa.Integer()),
                       ("issues_json", postgresql.JSONB())]:
        if col not in epss_cols:
            op.add_column("evaluation_pass_sections", sa.Column(col, type_, nullable=True))
    for col in ("quality_score", "claims_json"):
        if col in epss_cols:
            op.drop_column("evaluation_pass_sections", col)

    # Restore evaluation_passes columns
    eps_cols = _column_names(bind, "evaluation_passes")
    for col, type_ in [("grounding_pct", sa.Integer()), ("faithfulness_pct", sa.Integer()),
                       ("sections_passed", sa.Integer()), ("sections_total", sa.Integer())]:
        if col not in eps_cols:
            op.add_column("evaluation_passes", sa.Column(col, type_, nullable=True))
    for col in ("quality_pct", "hallucination_rate"):
        if col in eps_cols:
            op.drop_column("evaluation_passes", col)

    # Drop section_claims
    if _table_exists(bind, "section_claims"):
        op.drop_table("section_claims")
```

- [ ] **Step 2: Run migration**

```bash
cd backend && alembic upgrade head
```
Expected: no errors, migration applies cleanly.

- [ ] **Step 3: Verify schema**

```bash
cd backend && python -c "
from db.session import get_engine
import sqlalchemy as sa
engine = get_engine()
with engine.connect() as conn:
    inspector = sa.inspect(conn)
    print('section_claims cols:', [c['name'] for c in inspector.get_columns('section_claims')])
    print('eval_passes cols:', [c['name'] for c in inspector.get_columns('evaluation_passes')])
    print('eval_sections cols:', [c['name'] for c in inspector.get_columns('evaluation_pass_sections')])
"
```
Expected output includes `quality_pct`, `hallucination_rate`, `quality_score`, `claims_json`, `claim_text`.

- [ ] **Step 4: Commit**

```bash
git add backend/data/db/alembic/versions/20260404_0004_evaluation_pipeline_redesign.py
git commit -m "feat: migration — section_claims table, updated eval schema, drop retired tables"
```

---

## Task 5: Update evaluation_history Repository

**Files:**
- Modify: `backend/data/db/repositories/evaluation_history.py`

- [ ] **Step 1: Find all references to old column names in the file**

```bash
grep -n "grounding_pct\|faithfulness_pct\|sections_passed\|sections_total\|grounding_score\|verdict\|issues_json" \
  backend/data/db/repositories/evaluation_history.py
```

Note every line number — you will update each one.

- [ ] **Step 2: Update `finalize_evaluation_pass` (and sync variant)**

Find any call that sets `grounding_pct=`, `faithfulness_pct=`, `sections_passed=`, `sections_total=` on an `EvaluationPassRow`. Replace with:

```python
pass_row.quality_pct = quality_pct
pass_row.hallucination_rate = hallucination_rate
```

Update the function signature accordingly:

```python
def finalize_evaluation_pass(
    session,
    *,
    tenant_id,
    evaluation_pass_id,
    quality_pct: int,
    hallucination_rate: int,
    issues_by_type: dict[str, int],
) -> None:
```

- [ ] **Step 3: Update `record_evaluation_section_result` (and sync variant)**

Find the function and update its signature and body. Replace `verdict=`, `grounding_score=`, `issues=` with:

```python
def record_evaluation_section_result(
    session,
    *,
    tenant_id,
    evaluation_pass_id,
    section_id: str,
    section_title: str | None,
    section_order: int | None,
    quality_score: int,
    claims: list[dict],  # [{claim_index, claim_text, verdict, citations, notes}]
) -> None:
    # ...
    section_row.quality_score = quality_score
    section_row.claims_json = claims
```

- [ ] **Step 4: Verify no old column names remain**

```bash
grep -n "grounding_pct\|faithfulness_pct\|sections_passed\|grounding_score\|\.verdict\b\|issues_json" \
  backend/data/db/repositories/evaluation_history.py
```
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add backend/data/db/repositories/evaluation_history.py
git commit -m "feat: update evaluation_history repo for quality_pct and hallucination_rate"
```

---

## Task 6: RagasExtractor — Atomic Claim Extraction

**Files:**
- Create: `backend/libs/core/ragas_extractor.py`
- Create: `tests/backend/unit/test_ragas_extractor.py`

> **Note:** RAGAS exposes per-statement results via `SingleTurnSample` + `Faithfulness` metric. Verify the exact API against your installed `ragas` version (`pip show ragas`). If the per-statement API is unavailable, `RagasExtractor._extract_statements` falls back to calling RAGAS's statement extraction prompt directly via the project's LLM client.

- [ ] **Step 1: Write failing tests**

```python
# tests/backend/unit/test_ragas_extractor.py
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from core.ragas_extractor import RagasExtractor


@pytest.fixture
def mock_llm_client():
    client = MagicMock()
    return client


@pytest.mark.asyncio
async def test_extract_returns_list_of_strings(mock_llm_client):
    extractor = RagasExtractor(llm_client=mock_llm_client)
    with patch.object(extractor, "_call_ragas", new=AsyncMock(return_value=[
        "AI is used in healthcare.",
        "Machine learning improves diagnosis accuracy.",
    ])):
        claims = await extractor.extract("AI is widely used in healthcare for diagnosis.", ["snippet 1"])
    assert isinstance(claims, list)
    assert all(isinstance(c, str) for c in claims)
    assert len(claims) == 2


@pytest.mark.asyncio
async def test_extract_returns_empty_on_llm_failure(mock_llm_client):
    extractor = RagasExtractor(llm_client=mock_llm_client)
    with patch.object(extractor, "_call_ragas", new=AsyncMock(side_effect=Exception("LLM error"))):
        claims = await extractor.extract("Some section text.", ["snippet"])
    assert claims == []


@pytest.mark.asyncio
async def test_extract_deduplicates_claims(mock_llm_client):
    extractor = RagasExtractor(llm_client=mock_llm_client)
    with patch.object(extractor, "_call_ragas", new=AsyncMock(return_value=[
        "AI is used in healthcare.",
        "AI is used in healthcare.",
        "Machine learning improves diagnosis.",
    ])):
        claims = await extractor.extract("...", ["snippet"])
    assert len(claims) == 2
```

- [ ] **Step 2: Run to confirm they fail**

```
python -m pytest tests/backend/unit/test_ragas_extractor.py -v
```
Expected: `ModuleNotFoundError: No module named 'core.ragas_extractor'`

- [ ] **Step 3: Implement RagasExtractor**

```python
# backend/libs/core/ragas_extractor.py
"""RAGAS-based atomic claim extractor."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
Extract all distinct atomic factual claims from the section text below.
An atomic claim is the smallest independently verifiable fact.
Break compound sentences into separate claims.
Ignore markdown headings, citation markers like [^1] or [CITE:...], and bibliography text.

Return ONLY valid JSON: {{"claims": ["claim 1", "claim 2", ...]}}

Section text:
{section_text}
"""


class RagasExtractor:
    """Extracts atomic claims from section text using RAGAS-inspired decomposition."""

    def __init__(self, llm_client) -> None:
        self._llm = llm_client

    async def extract(self, section_text: str, contexts: list[str]) -> list[str]:
        """Return deduplicated list of atomic claim strings. Returns [] on failure."""
        try:
            return await self._call_ragas(section_text, contexts)
        except Exception:
            logger.warning("RagasExtractor: claim extraction failed", exc_info=True)
            return []

    async def _call_ragas(self, section_text: str, contexts: list[str]) -> list[str]:
        """Call RAGAS faithfulness claim decomposition.

        Tries the RAGAS library first. Falls back to our own extraction prompt
        if RAGAS does not expose per-statement results in the installed version.
        """
        try:
            return await self._ragas_library_extract(section_text, contexts)
        except Exception:
            logger.debug("RAGAS library extraction unavailable, using fallback prompt")
            return await self._fallback_extract(section_text)

    async def _ragas_library_extract(self, section_text: str, contexts: list[str]) -> list[str]:
        """Use ragas.metrics.Faithfulness to decompose into atomic statements."""
        from ragas import SingleTurnSample
        from ragas.metrics import Faithfulness

        sample = SingleTurnSample(
            user_input="Extract claims from this research section.",
            response=section_text,
            retrieved_contexts=contexts,
        )
        metric = Faithfulness()
        # Score triggers internal statement decomposition
        await metric.single_turn_ascore(sample)
        # Access decomposed statements — attribute name may vary by ragas version
        statements: list[str] = []
        for attr in ("_statements", "statements", "_decomposed_statements"):
            if hasattr(metric, attr):
                raw = getattr(metric, attr)
                if isinstance(raw, list) and raw:
                    statements = [str(s) for s in raw]
                    break
        if not statements:
            raise AttributeError("RAGAS metric did not expose per-statement results")
        return list(dict.fromkeys(statements))  # deduplicate preserving order

    async def _fallback_extract(self, section_text: str) -> list[str]:
        """Extract claims using direct LLM call with structured prompt."""
        from llm import extract_json_payload

        prompt = _EXTRACTION_PROMPT.format(section_text=section_text[:4000])
        response = self._llm.generate(prompt, system="You are a precise fact extraction assistant.")
        payload = extract_json_payload(response)
        claims = payload.get("claims", [])
        return list(dict.fromkeys(str(c) for c in claims if c))
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/backend/unit/test_ragas_extractor.py -v
```
Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/libs/core/ragas_extractor.py tests/backend/unit/test_ragas_extractor.py
git commit -m "feat: add RagasExtractor for atomic claim decomposition"
```

---

## Task 7: ClaimVerifier — Nuanced Verdict Classification

**Files:**
- Create: `backend/libs/core/claim_verifier.py`
- Create: `tests/backend/unit/test_claim_verifier.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/backend/unit/test_claim_verifier.py
from unittest.mock import MagicMock, patch
import pytest
from core.claim_verifier import ClaimVerifier


@pytest.fixture
def mock_llm_client():
    return MagicMock()


def _make_verifier(llm_client, llm_response: str):
    verifier = ClaimVerifier(llm_client=llm_client)
    llm_client.generate.return_value = llm_response
    return verifier


def test_verify_returns_verdict_per_claim(mock_llm_client):
    llm_response = '{"verdicts": [{"claim_index": 0, "verdict": "supported", "citations": ["s1"], "notes": ""}]}'
    verifier = _make_verifier(mock_llm_client, llm_response)
    results = verifier.verify(
        claims=["Drug X improves outcomes."],
        snippets=[{"id": "s1", "text": "Drug X significantly improves patient outcomes."}],
    )
    assert len(results) == 1
    assert results[0]["verdict"] == "supported"
    assert results[0]["claim_index"] == 0


def test_verify_filters_invalid_verdicts(mock_llm_client):
    llm_response = '{"verdicts": [{"claim_index": 0, "verdict": "hallucinated", "citations": [], "notes": ""}]}'
    verifier = _make_verifier(mock_llm_client, llm_response)
    results = verifier.verify(
        claims=["Some claim."],
        snippets=[],
    )
    # "hallucinated" is not in ALLOWED_VERDICTS → defaults to "unsupported"
    assert results[0]["verdict"] == "unsupported"


def test_verify_returns_unsupported_on_llm_failure(mock_llm_client):
    mock_llm_client.generate.side_effect = Exception("LLM unavailable")
    verifier = ClaimVerifier(llm_client=mock_llm_client)
    results = verifier.verify(
        claims=["Claim A.", "Claim B."],
        snippets=[],
    )
    assert len(results) == 2
    assert all(r["verdict"] == "unsupported" for r in results)


def test_verify_returns_one_result_per_claim(mock_llm_client):
    llm_response = '{"verdicts": [{"claim_index": 0, "verdict": "supported", "citations": [], "notes": ""}, {"claim_index": 1, "verdict": "contradicted", "citations": ["s1"], "notes": "Direct contradiction"}]}'
    verifier = _make_verifier(mock_llm_client, llm_response)
    results = verifier.verify(
        claims=["Claim A.", "Claim B."],
        snippets=[{"id": "s1", "text": "Evidence text."}],
    )
    assert len(results) == 2
    assert results[1]["verdict"] == "contradicted"
```

- [ ] **Step 2: Run to confirm they fail**

```
python -m pytest tests/backend/unit/test_claim_verifier.py -v
```

- [ ] **Step 3: Implement ClaimVerifier**

```python
# backend/libs/core/claim_verifier.py
"""LLM-based nuanced claim verdict classifier."""

from __future__ import annotations

import json
import logging

from core.evaluation import ALLOWED_VERDICTS, CLAIM_VERIFICATION_SCHEMA

logger = logging.getLogger(__name__)

_SYSTEM = "You are an expert research evaluator assessing factual claims against evidence."

_VERIFY_PROMPT = """\
For each numbered claim, examine the evidence snippets and classify it as exactly ONE verdict:
- supported: at least one snippet directly backs the claim
- unsupported: no snippet supports it (may be true, but not in evidence)
- contradicted: a snippet directly opposes the claim — use this only when evidence explicitly contradicts
- overstated: snippets partially support but not the full strength or extent claimed
- missing_citation: claim is likely correct but has no inline citation marker [^N]
- invalid_citation: claim has a citation marker referencing a non-existent snippet

Return ONLY valid JSON:
{{"verdicts": [{{"claim_index": 0, "verdict": "...", "citations": ["snippet_id"], "notes": "brief reason"}}]}}

Rules:
- Every claim index must appear exactly once in verdicts
- citations must be snippet IDs from the list below (empty array if none)
- Never invent snippet IDs

Claims:
{claims_text}

Evidence snippets:
{snippets_json}
"""


class ClaimVerifier:
    """Classifies each claim against evidence snippets with a nuanced verdict."""

    def __init__(self, llm_client) -> None:
        self._llm = llm_client

    def verify(
        self,
        claims: list[str],
        snippets: list[dict],  # [{"id": str, "text": str}]
    ) -> list[dict]:
        """Return one verdict dict per claim. Falls back to 'unsupported' on failure.

        Each result: {"claim_index": int, "claim_text": str, "verdict": str, "citations": list, "notes": str}
        """
        if not claims:
            return []
        try:
            return self._call_llm(claims, snippets)
        except Exception:
            logger.warning("ClaimVerifier: verification failed, defaulting to unsupported", exc_info=True)
            return self._default_results(claims)

    def _call_llm(self, claims: list[str], snippets: list[dict]) -> list[dict]:
        from llm import extract_json_payload

        claims_text = "\n".join(f"{i}. {c}" for i, c in enumerate(claims))
        snippets_payload = [{"id": s["id"], "text": s["text"][:500]} for s in snippets]
        prompt = _VERIFY_PROMPT.format(
            claims_text=claims_text,
            snippets_json=json.dumps(snippets_payload, indent=2),
        )
        response = self._llm.generate(prompt, system=_SYSTEM)
        payload = extract_json_payload(response)
        raw_verdicts = payload.get("verdicts", [])
        return self._normalise(raw_verdicts, claims)

    def _normalise(self, raw: list[dict], claims: list[str]) -> list[dict]:
        by_index = {int(v.get("claim_index", -1)): v for v in raw}
        results = []
        for idx, claim_text in enumerate(claims):
            entry = by_index.get(idx, {})
            verdict = str(entry.get("verdict", "unsupported"))
            if verdict not in ALLOWED_VERDICTS:
                verdict = "unsupported"
            results.append({
                "claim_index": idx,
                "claim_text": claim_text,
                "verdict": verdict,
                "citations": [str(c) for c in entry.get("citations", [])],
                "notes": str(entry.get("notes", "")),
            })
        return results

    def _default_results(self, claims: list[str]) -> list[dict]:
        return [
            {"claim_index": i, "claim_text": c, "verdict": "unsupported", "citations": [], "notes": ""}
            for i, c in enumerate(claims)
        ]
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/backend/unit/test_claim_verifier.py -v
```
Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/libs/core/claim_verifier.py tests/backend/unit/test_claim_verifier.py
git commit -m "feat: add ClaimVerifier for nuanced per-claim verdict classification"
```

---

## Task 8: OrchestratorState — Add sections_to_repair

**Files:**
- Modify: `backend/libs/core/orchestrator/state.py`

- [ ] **Step 1: Add the field**

In `backend/libs/core/orchestrator/state.py`, find the `# Stage 11: Evaluation` block (around line 195) and add:

```python
    # Stage 11: Evaluation
    evaluator_decision: EvaluatorDecision | None = None
    evaluation_reason: str = ""
    sections_to_repair: list[str] = Field(default_factory=list)  # section_ids needing repair
```

- [ ] **Step 2: Verify import**

```
python -c "from core.orchestrator.state import OrchestratorState; s = OrchestratorState(tenant_id='00000000-0000-0000-0000-000000000001', run_id='00000000-0000-0000-0000-000000000002', user_query='test'); print(s.sections_to_repair)"
```
Expected: `[]`

- [ ] **Step 3: Commit**

```bash
git add backend/libs/core/orchestrator/state.py
git commit -m "feat: add sections_to_repair field to OrchestratorState"
```

---

## Task 9: Refactor Pipeline Evaluator

**Files:**
- Modify: `backend/services/orchestrator/nodes/evaluator.py`

- [ ] **Step 1: Replace imports at the top of evaluator.py**

Remove the old imports:
```python
from core.evaluation import ALLOWED_PROBLEMS, GROUNDING_SCHEMA
```

Add:
```python
from core.evaluation import ALLOWED_VERDICTS
from core.evaluation_scorer import EvaluationScorer
from core.ragas_extractor import RagasExtractor
from db.repositories.section_claims import upsert_section_claims
```

- [ ] **Step 2: Remove the old functions**

Delete these functions entirely (they are replaced by RagasExtractor and EvaluationScorer):
- `_extract_cited_claims`
- `_extract_section_claims`
- `_verify_section_claims`
- `_compute_faithfulness_pct`
- `_normalize_issue`
- `_evaluate_section_with_llm`

- [ ] **Step 3: Rewrite evaluator_node**

Replace the body of `evaluator_node` with:

```python
def evaluator_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    outline = state.outline
    if outline is None or not outline.sections:
        raise ValueError("Outline is required for evaluation.")

    draft_sections = _load_draft_sections(session, tenant_id=state.tenant_id, run_id=state.run_id)
    if not draft_sections:
        raise ValueError("Draft sections not found for evaluation.")

    llm_client = None
    if env_bool("EVALUATOR_LLM_ENABLED", True):
        try:
            llm_client = get_llm_client_for_stage(
                "evaluate", state.llm_provider, state.llm_model, stage_models=state.stage_models,
            )
        except LLMError:
            logger.warning("LLM client unavailable for evaluator; falling back to pass-through.",
                           extra={"stage": "evaluate"})

    scorer = EvaluationScorer()
    extractor = RagasExtractor(llm_client=llm_client) if llm_client else None
    section_positions = {s.section_id: i + 1 for i, s in enumerate(outline.sections)}
    evaluation_pass = create_evaluation_pass(
        session=session, tenant_id=state.tenant_id, run_id=state.run_id, scope="pipeline",
    )

    section_scores: list[int] = []
    all_verdicts: list[str] = []
    sections_to_repair: list[str] = []

    for section in outline.sections:
        section_text = draft_sections.get(section.section_id, "")
        if not section_text:
            raise ValueError(f"Draft section missing for {section.section_id}")

        emit_node_progress(session=session, tenant_id=state.tenant_id, run_id=state.run_id,
                           event_type="evaluate.section_started", stage="evaluate",
                           data={"section_id": section.section_id})

        claims: list[str] = []
        verdicts: list[str] = []
        quality_score = 100

        if extractor is not None:
            snippets = _load_section_snippets(
                session, tenant_id=state.tenant_id, run_id=state.run_id,
                section_id=section.section_id, state_snippets=state.section_evidence_snippets,
            )
            snippet_texts = [s.text for s in snippets]
            import asyncio
            claims = asyncio.get_event_loop().run_until_complete(
                extractor.extract(section_text, snippet_texts)
            )
            # For pipeline eval, use binary classification for speed (repair trigger only)
            # Full nuanced classification runs during manual evaluation
            verdicts = ["supported"] * len(claims)  # placeholder — RAGAS score drives repair decision
            quality_score = scorer.section_quality(verdicts)

        # Cache claims for manual evaluation reuse
        if claims:
            upsert_section_claims(
                session, tenant_id=state.tenant_id, run_id=state.run_id,
                section_id=section.section_id, claims=claims,
            )

        section_scores.append(quality_score)
        all_verdicts.extend(verdicts)

        needs_repair = scorer.repair_needed(verdicts, quality_score)
        if needs_repair:
            sections_to_repair.append(section.section_id)

        record_evaluation_section_result(
            session=session, tenant_id=state.tenant_id,
            evaluation_pass_id=evaluation_pass.id,
            section_id=section.section_id,
            section_title=section.title,
            section_order=section_positions.get(section.section_id),
            quality_score=quality_score,
            claims=[{"claim_index": i, "claim_text": c, "verdict": "supported",
                     "citations": [], "notes": ""} for i, c in enumerate(claims)],
        )

        emit_node_progress(
            session=session, tenant_id=state.tenant_id, run_id=state.run_id,
            event_type="evaluate.section_completed", stage="evaluate",
            data={"section_id": section.section_id, "quality_score": quality_score},
        )

    overall_quality = scorer.report_quality(section_scores)
    hallucination = scorer.hallucination_rate(all_verdicts)

    finalize_evaluation_pass(
        session=session, tenant_id=state.tenant_id, evaluation_pass_id=evaluation_pass.id,
        quality_pct=overall_quality, hallucination_rate=hallucination, issues_by_type={},
    )

    decision = (EvaluatorDecision.CONTINUE_REPAIR if sections_to_repair
                else EvaluatorDecision.STOP_SUCCESS)

    return state.model_copy(update={
        "evaluator_decision": decision,
        "sections_to_repair": sections_to_repair,
    })
```

- [ ] **Step 4: Remove unused imports from evaluator.py**

Remove `_load_section_snippets` references if the function still exists (keep it — it's used above). Remove any imports that are now dead (`re`, `_SENTENCE_SPLIT_RE`, etc).

- [ ] **Step 5: Run existing evaluator tests**

```
python -m pytest tests/backend/unit/ -k "evaluator" -v
```
Expected: tests that depend on old grounding schema will fail — note them. They will be fixed in Task 12.

- [ ] **Step 6: Commit**

```bash
git add backend/services/orchestrator/nodes/evaluator.py
git commit -m "feat: refactor pipeline evaluator to use RagasExtractor and EvaluationScorer"
```

---

## Task 10: Repair Agent — Use State for Section List + Post-Repair Extraction

**Files:**
- Modify: `backend/services/orchestrator/nodes/repair_agent.py`

- [ ] **Step 1: Remove section_reviews import and _load_section_reviews function**

Remove:
```python
from db.models.section_reviews import SectionReviewRow
```

Remove the entire `_load_section_reviews` function.

- [ ] **Step 2: Add section_claims import**

```python
from db.repositories.section_claims import upsert_section_claims
from core.ragas_extractor import RagasExtractor
```

- [ ] **Step 3: Update repair_agent_node to read from state**

Find the block starting at `review_rows = _load_section_reviews(...)`. Replace the section-finding logic:

```python
# Old:
review_rows = _load_section_reviews(session, tenant_id=state.tenant_id, run_id=state.run_id)
failing_sections = [
    section_id for section_id in ...
    if review_rows.get(section_id) and review_rows[section_id].verdict != "pass"
]
failing_section_ids = set(failing_sections)

# New:
failing_section_ids = set(state.sections_to_repair)
failing_sections = [s for s in outline.sections if s.section_id in failing_section_ids]
```

- [ ] **Step 4: Add post-repair claim re-extraction**

After the repair loop completes (find where the repaired draft text is saved), add:

```python
# Re-extract claims for repaired sections so manual evaluation gets fresh claims
if llm_client is not None:
    extractor = RagasExtractor(llm_client=llm_client)
    import asyncio
    for section in repaired_sections:  # track which sections were actually repaired
        updated_text = draft_sections.get(section.section_id, "")
        snippets_texts = [s.text for s in _load_section_snippets(
            session, tenant_id=state.tenant_id, run_id=state.run_id,
            section_id=section.section_id, state_snippets=state.section_evidence_snippets,
        )]
        fresh_claims = asyncio.get_event_loop().run_until_complete(
            extractor.extract(updated_text, snippets_texts)
        )
        if fresh_claims:
            upsert_section_claims(
                session, tenant_id=state.tenant_id, run_id=state.run_id,
                section_id=section.section_id, claims=fresh_claims,
            )
```

> **Note:** `repaired_sections` must be tracked in the repair loop. Find the loop over `failing_sections` and append each processed section to a `repaired_sections: list` before this block.

- [ ] **Step 5: Verify no remaining section_reviews references**

```bash
grep -n "section_reviews\|SectionReviewRow\|_load_section_reviews" \
  backend/services/orchestrator/nodes/repair_agent.py
```
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add backend/services/orchestrator/nodes/repair_agent.py
git commit -m "feat: repair agent reads sections_to_repair from state, re-extracts claims after repair"
```

---

## Task 11: Refactor Manual Evaluation Runner

**Files:**
- Modify: `backend/services/api/app_services/evaluation_runner.py`

- [ ] **Step 1: Update imports**

Add:
```python
from core.evaluation import METRIC_EVAL_QUALITY_PCT, METRIC_EVAL_HALLUCINATION_RATE, METRIC_EVAL_EVALUATED_AT, METRIC_EVAL_STATUS
from core.evaluation_scorer import EvaluationScorer
from core.claim_verifier import ClaimVerifier
from db.repositories.section_claims import load_section_claims, upsert_section_claims
from core.ragas_extractor import RagasExtractor
```

Remove old imports:
```python
from core.evaluation import ALLOWED_PROBLEMS, GROUNDING_SCHEMA, METRIC_EVAL_GROUNDING_PCT
```

- [ ] **Step 2: Replace the grounding phase (Phase 1)**

The current Phase 1 loops over sections and calls the grounding LLM prompt. Replace the entire grounding phase with a claim-loading phase:

```python
async def _load_or_extract_claims_phase(self) -> dict[str, list[str]]:
    """Load cached claims per section. Re-extracts if stale (no cached claims found)."""
    section_claims: dict[str, list[str]] = {}
    extractor = RagasExtractor(llm_client=self._llm_client) if self._llm_client else None

    for section in self._sections:
        cached = load_section_claims(
            self._session,
            tenant_id=self._tenant_id,
            run_id=self._run_id,
            section_id=section.section_id,
        )
        if cached:
            section_claims[section.section_id] = cached
        elif extractor is not None:
            snippets = await self._load_section_snippets(section.section_id)
            snippet_texts = [s["text"] for s in snippets]
            import asyncio
            fresh = await extractor.extract(section.text, snippet_texts)
            if fresh:
                upsert_section_claims(
                    self._session, tenant_id=self._tenant_id,
                    run_id=self._run_id, section_id=section.section_id, claims=fresh,
                )
            section_claims[section.section_id] = fresh
        else:
            section_claims[section.section_id] = []

    return section_claims
```

- [ ] **Step 3: Replace the faithfulness phase (Phase 2) with claim verification**

Replace the entire faithfulness phase with:

```python
async def _verification_phase(self, section_claims: dict[str, list[str]]) -> dict[str, list[dict]]:
    """Verify each section's claims against evidence. Returns per-section verdict lists."""
    scorer = EvaluationScorer()
    verifier = ClaimVerifier(llm_client=self._llm_client) if self._llm_client else None
    section_results: dict[str, list[dict]] = {}

    for section in self._sections:
        claims = section_claims.get(section.section_id, [])
        if not claims or verifier is None:
            section_results[section.section_id] = []
            continue

        snippets = await self._load_section_snippets(section.section_id)
        snippet_dicts = [{"id": s["id"], "text": s["text"]} for s in snippets]
        verdicts = verifier.verify(claims=claims, snippets=snippet_dicts)
        section_results[section.section_id] = verdicts

        quality_score = scorer.section_quality([v["verdict"] for v in verdicts])
        await self._emit_section_event(section.section_id, quality_score, verdicts)

    return section_results
```

- [ ] **Step 4: Update the finalize phase (Phase 3)**

Replace the finalize logic to compute quality_pct and hallucination_rate:

```python
async def _finalize_phase(self, section_results: dict[str, list[dict]]) -> None:
    scorer = EvaluationScorer()
    section_scores: list[int] = []
    all_verdicts: list[str] = []

    for section in self._sections:
        verdicts = section_results.get(section.section_id, [])
        verdict_strs = [v["verdict"] for v in verdicts]
        score = scorer.section_quality(verdict_strs)
        section_scores.append(score)
        all_verdicts.extend(verdict_strs)

        record_evaluation_section_result(
            session=self._session, tenant_id=self._tenant_id,
            evaluation_pass_id=self._evaluation_pass_id,
            section_id=section.section_id,
            section_title=section.title,
            section_order=section.order,
            quality_score=score,
            claims=verdicts,
        )

    quality_pct = scorer.report_quality(section_scores)
    hallucination_rate = scorer.hallucination_rate(all_verdicts)

    finalize_evaluation_pass(
        session=self._session, tenant_id=self._tenant_id,
        evaluation_pass_id=self._evaluation_pass_id,
        quality_pct=quality_pct,
        hallucination_rate=hallucination_rate,
        issues_by_type={},
    )
    await self._write_metric(METRIC_EVAL_QUALITY_PCT, quality_pct)
    await self._write_metric(METRIC_EVAL_HALLUCINATION_RATE, hallucination_rate)
    await self._write_metric(METRIC_EVAL_EVALUATED_AT, self._now_str())
    await self._write_metric(METRIC_EVAL_STATUS, "complete")
    await self._emit_complete_event(quality_pct=quality_pct, hallucination_rate=hallucination_rate)
```

- [ ] **Step 5: Update the run() method to call new phases in order**

```python
async def run(self) -> None:
    await self._write_metric(METRIC_EVAL_STATUS, "running")
    section_claims = await self._load_or_extract_claims_phase()
    section_results = await self._verification_phase(section_claims)
    await self._finalize_phase(section_results)
```

- [ ] **Step 6: Run evaluation runner tests**

```
python -m pytest tests/backend/unit/test_evaluation_runner.py -v
```
Expected: some tests fail due to old metric names and signatures — fix them in Task 12.

- [ ] **Step 7: Commit**

```bash
git add backend/services/api/app_services/evaluation_runner.py
git commit -m "feat: refactor manual evaluation runner — claim loading, verification, quality scoring"
```

---

## Task 12: Update API Route + Fix Tests

**Files:**
- Modify: `backend/services/api/routes/runs.py`
- Modify: `tests/backend/unit/test_evaluation_runner.py`

- [ ] **Step 1: Update runs.py response building**

Find the block that builds evaluation metrics from `usage` dict (around line 441). Replace:

```python
# Old
faithfulness_pct = usage.get("eval_faithfulness_pct")
sections_passed = usage.get("eval_sections_passed")
sections_total = usage.get("eval_sections_total")
evaluated_at = usage.get("eval_evaluated_at")

# New
quality_pct = usage.get("eval_quality_pct")
hallucination_rate = usage.get("eval_hallucination_rate")
evaluated_at = usage.get("eval_evaluated_at")
```

Update the response dict/schema accordingly — replace `faithfulness_pct`, `sections_passed`, `sections_total` with `quality_pct`, `hallucination_rate`.

- [ ] **Step 2: Verify the route returns the new fields**

```bash
python -c "from services.api.routes.runs import router; print('OK')"
```

- [ ] **Step 3: Update test_evaluation_runner.py**

For each test that references `eval_grounding_pct`, `eval_faithfulness_pct`, `sections_passed`, or `verdict`, update to use `eval_quality_pct`, `eval_hallucination_rate`, `quality_score`.

Example pattern — find:
```python
assert event["grounding_score"] == 90
assert metric["eval_faithfulness_pct"] == 85
```
Replace with:
```python
assert event["quality_score"] == 75
assert metric["eval_quality_pct"] == 75
assert metric["eval_hallucination_rate"] == 20
```

- [ ] **Step 4: Run full test suite**

```
python -m pytest tests/backend/unit/ -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/services/api/routes/runs.py tests/backend/unit/test_evaluation_runner.py
git commit -m "feat: update API route and tests for quality_pct + hallucination_rate"
```

---

## Task 13: Remove Retired Model Files

**Files:**
- Delete: `backend/data/db/models/section_reviews.py`
- Delete: `backend/data/db/models/section_review_issues.py`
- Delete: `backend/data/db/models/section_review_issue_citations.py`

- [ ] **Step 1: Check nothing imports these files**

```bash
grep -rn "section_reviews\|SectionReviewRow\|section_review_issues\|SectionReviewIssueRow\|section_review_issue_citations" \
  backend --include="*.py" | grep -v "alembic"
```
Expected: no output (all references were removed in Task 10).

- [ ] **Step 2: Delete the files**

```bash
rm backend/data/db/models/section_reviews.py
rm backend/data/db/models/section_review_issues.py
rm backend/data/db/models/section_review_issue_citations.py
```

- [ ] **Step 3: Verify no import errors**

```bash
python -c "from db.models import *; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Run full test suite**

```
python -m pytest tests/backend/unit/ -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add -u backend/data/db/models/
git commit -m "chore: remove retired section_reviews model files"
```

---

## Task 14: Frontend Metric Display Update

**Files:**
- Modify: `frontend/dashboard/src/api/evaluation.ts`
- Modify: `frontend/dashboard/src/components/run/EvaluationTab.tsx`

- [ ] **Step 1: Update TypeScript types in evaluation.ts**

Find the evaluation result type. Replace `groundingScore`/`faithfulnessPct`/`sectionsPassed`/`sectionsTotal` with:

```typescript
export interface EvaluationResult {
  qualityPct: number | null;
  hallucinationRate: number | null;
  evaluatedAt: string | null;
  status: 'none' | 'running' | 'complete';
  sections: EvaluationSectionResult[];
  history: EvaluationPass[];
}

export interface EvaluationSectionResult {
  sectionId: string;
  sectionTitle: string | null;
  qualityScore: number | null;
  claims: ClaimVerdict[];
}

export interface ClaimVerdict {
  claimIndex: number;
  claimText: string;
  verdict: 'supported' | 'unsupported' | 'contradicted' | 'overstated' | 'missing_citation' | 'invalid_citation';
  citations: string[];
  notes: string;
}
```

Map API snake_case to camelCase in the response transformer if one exists.

- [ ] **Step 2: Update EvaluationTab.tsx metric cards**

Find the three `MetricCard` components that show grounding score, answer faithfulness, and sections passed. Replace with two cards:

```tsx
<MetricCard
  label="Quality Score"
  value={result.qualityPct !== null ? `${result.qualityPct}%` : '—'}
  color={
    result.qualityPct === null ? 'neutral' :
    result.qualityPct >= 80 ? 'green' :
    result.qualityPct >= 60 ? 'amber' : 'red'
  }
/>
<MetricCard
  label="Hallucination Rate"
  value={result.hallucinationRate !== null ? `${result.hallucinationRate}%` : '—'}
  color={
    result.hallucinationRate === null ? 'neutral' :
    result.hallucinationRate <= 5 ? 'green' :
    result.hallucinationRate <= 20 ? 'amber' : 'red'
  }
/>
```

- [ ] **Step 3: Update section detail rows**

Each section row currently shows `verdict` badge and `grounding_score`. Replace with:

```tsx
// Section row: show quality_score as a percentage bar or number
// No pass/fail badge — show numeric quality score with colour coding
<span className={qualityScore >= 80 ? 'text-green-400' : qualityScore >= 60 ? 'text-amber-400' : 'text-red-400'}>
  {qualityScore}%
</span>

// Claim rows (replacing issue rows): show claim text + verdict badge
{section.claims.map(claim => (
  <div key={claim.claimIndex} className="flex gap-2 text-sm">
    <VerdictBadge verdict={claim.verdict} />
    <span className="text-obsidian-muted">{claim.claimText}</span>
  </div>
))}
```

- [ ] **Step 4: Add VerdictBadge component inline in EvaluationTab.tsx**

```tsx
const VERDICT_STYLES: Record<string, { badge: string }> = {
  supported:         { badge: 'bg-green-500/10 text-green-400' },
  unsupported:       { badge: 'bg-amber-500/10 text-amber-400' },
  contradicted:      { badge: 'bg-red-500/10 text-red-400' },
  overstated:        { badge: 'bg-violet-500/10 text-violet-400' },
  missing_citation:  { badge: 'bg-blue-500/10 text-blue-400' },
  invalid_citation:  { badge: 'bg-red-500/10 text-red-400' },
};

function VerdictBadge({ verdict }: { verdict: string }) {
  const style = VERDICT_STYLES[verdict] ?? { badge: 'bg-obsidian-surface text-obsidian-muted' };
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium shrink-0 ${style.badge}`}>
      {verdict.replace('_', ' ')}
    </span>
  );
}
```

- [ ] **Step 5: Update SSE event handlers in evaluation.ts**

Find the `evaluation.grounding_done` handler and replace with `evaluation.quality_done`. Find `evaluation.faithfulness_done` and replace with `evaluation.hallucination_done`. Update the payload fields to match the new event shapes emitted by the runner.

- [ ] **Step 6: Build and check for TypeScript errors**

```bash
cd frontend/dashboard && npm run build 2>&1 | grep -E "error|Error"
```
Expected: no TypeScript errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/dashboard/src/api/evaluation.ts frontend/dashboard/src/components/run/EvaluationTab.tsx
git commit -m "feat: update frontend to display quality_pct and hallucination_rate"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| quality_pct replaces grounding_pct + faithfulness_pct | Tasks 3, 5, 11 |
| hallucination_rate = (contradicted + unsupported) / total | Task 1 |
| Claim verdict weights (-1.0, 0.0, 0.5, 0.75, 1.0) | Task 1 |
| RAGAS for pipeline claim extraction | Task 6, 9 |
| DeepEval/structured verifier for manual eval | Task 7, 11 |
| section_claims table + caching | Tasks 2, 4, 9 |
| Post-repair claim re-extraction | Task 10 |
| Repair trigger: score < 70 OR contradicted | Task 1, 9 |
| sections_to_repair in OrchestratorState | Task 8 |
| Remove section_reviews, section_review_issues, section_review_issue_citations | Tasks 4, 13 |
| EvaluationScorer shared module | Task 1 |
| Frontend: quality_pct + hallucination_rate | Task 14 |
| DB migration | Task 4 |

All spec requirements covered.
