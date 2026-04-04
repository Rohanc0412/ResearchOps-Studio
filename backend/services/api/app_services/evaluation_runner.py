"""
On-demand evaluation runner for research reports.

Loads cached claims (extracted during pipeline evaluation), verifies each claim
against evidence snippets using ClaimVerifier, then computes quality_pct and
hallucination_rate with EvaluationScorer.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from core.claim_verifier import ClaimVerifier
from core.evaluation import (
    METRIC_EVAL_EVALUATED_AT,
    METRIC_EVAL_HALLUCINATION_RATE,
    METRIC_EVAL_QUALITY_PCT,
    METRIC_EVAL_STATUS,
)
from core.evaluation_scorer import EvaluationScorer
from core.ragas_extractor import RagasExtractor
from db.models.draft_sections import DraftSectionRow
from db.models.run_sections import RunSectionRow
from db.models.run_usage_metrics import RunUsageMetricRow
from db.models.section_claims import SectionClaimRow
from db.models.section_evidence import SectionEvidenceRow
from db.models.snapshots import SnapshotRow
from db.models.snippets import SnippetRow
from db.repositories.evaluation_history import (
    create_evaluation_pass,
    finalize_evaluation_pass,
    record_evaluation_section_result,
)
from llm import LLMError, get_llm_client_for_stage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class _SectionInfo:
    section_id: str
    title: str
    order: int
    text: str


class EvaluationRunner:
    """Runs on-demand quality evaluation for a completed research report."""

    def __init__(self, *, session: AsyncSession, tenant_id: UUID, run_id: UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.run_id = run_id
        self._evaluation_pass_id: UUID | None = None

    async def run(self) -> AsyncGenerator[dict, None]:
        llm_client = None
        try:
            llm_client = get_llm_client_for_stage("evaluate")
        except (LLMError, Exception):
            logger.warning("LLM client unavailable for evaluation runner; claim extraction disabled.")

        history_pass = await create_evaluation_pass(
            session=self.session,
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            scope="manual",
        )
        self._evaluation_pass_id = history_pass.id
        await self._write_metric(METRIC_EVAL_STATUS, "running")
        await self.session.flush()
        await self.session.commit()

        sections = await self._load_sections()
        if not sections:
            await self._write_metric(METRIC_EVAL_STATUS, "complete")
            await self._write_metric(METRIC_EVAL_QUALITY_PCT, None)
            await self._write_metric(METRIC_EVAL_HALLUCINATION_RATE, None)
            await self._write_metric(METRIC_EVAL_EVALUATED_AT, datetime.now(UTC).isoformat())
            await self.session.flush()
            await self.session.commit()
            yield {"type": "evaluation.complete", "quality_pct": None, "hallucination_rate": None}
            return

        yield {"type": "evaluation.started", "steps": 2}
        yield {"type": "evaluation.step", "step": 1, "label": "Verifying claims against evidence…"}

        # Phase 1: load cached claims (or re-extract if missing)
        section_claims = await self._load_or_extract_claims(sections, llm_client)

        # Phase 2: verify claims against evidence
        scorer = EvaluationScorer()
        verifier = ClaimVerifier(llm_client=llm_client) if llm_client else None
        section_results: dict[str, list[dict]] = {}

        for section in sections:
            yield {"type": "evaluation.section_started",
                   "section_id": section.section_id,
                   "section_title": section.title}

            claims = section_claims.get(section.section_id, [])
            verdicts: list[dict] = []
            if claims and verifier is not None:
                snippets = await self._load_section_snippets(section.section_id)
                snippet_dicts = [{"id": s["snippet_id"], "text": s["text"]} for s in snippets]
                verdicts = await asyncio.to_thread(
                    verifier.verify, claims=claims, snippets=snippet_dicts
                )
            section_results[section.section_id] = verdicts
            quality_score = scorer.section_quality([v["verdict"] for v in verdicts])
            yield {
                "type": "evaluation.section",
                "section_id": section.section_id,
                "section_title": section.title,
                "quality_score": quality_score,
                "verdicts": verdicts,
            }

        yield {"type": "evaluation.step", "step": 2, "label": "Computing final scores…"}

        # Phase 3: finalize
        section_scores: list[int] = []
        all_verdicts: list[str] = []

        for section in sections:
            verdicts = section_results.get(section.section_id, [])
            verdict_strs = [v["verdict"] for v in verdicts]
            score = scorer.section_quality(verdict_strs)
            section_scores.append(score)
            all_verdicts.extend(verdict_strs)

            await record_evaluation_section_result(
                session=self.session,
                tenant_id=self.tenant_id,
                evaluation_pass_id=self._evaluation_pass_id,
                section_id=section.section_id,
                section_title=section.title,
                section_order=section.order,
                quality_score=score,
                claims=verdicts,
            )

        quality_pct = scorer.report_quality(section_scores)
        hallucination_rate = scorer.hallucination_rate(all_verdicts)

        await finalize_evaluation_pass(
            session=self.session,
            tenant_id=self.tenant_id,
            evaluation_pass_id=self._evaluation_pass_id,
            quality_pct=quality_pct,
            hallucination_rate=hallucination_rate,
            issues_by_type={},
        )
        await self._write_metric(METRIC_EVAL_QUALITY_PCT, quality_pct)
        await self._write_metric(METRIC_EVAL_HALLUCINATION_RATE, hallucination_rate)
        await self._write_metric(METRIC_EVAL_EVALUATED_AT, datetime.now(UTC).isoformat())
        await self._write_metric(METRIC_EVAL_STATUS, "complete")
        await self.session.flush()
        await self.session.commit()

        yield {
            "type": "evaluation.complete",
            "quality_pct": quality_pct,
            "hallucination_rate": hallucination_rate,
        }

    async def _load_sections(self) -> list[_SectionInfo]:
        section_result = await self.session.execute(
            select(RunSectionRow)
            .where(RunSectionRow.tenant_id == self.tenant_id, RunSectionRow.run_id == self.run_id)
            .order_by(RunSectionRow.section_order)
        )
        section_rows = list(section_result.scalars().all())

        draft_result = await self.session.execute(
            select(DraftSectionRow.section_id, DraftSectionRow.text)
            .where(DraftSectionRow.tenant_id == self.tenant_id, DraftSectionRow.run_id == self.run_id)
        )
        drafts: dict[str, str] = {row.section_id: row.text for row in draft_result.all()}

        sections: list[_SectionInfo] = []
        for row in section_rows:
            text = drafts.get(row.section_id, "")
            if text:
                sections.append(_SectionInfo(
                    section_id=row.section_id,
                    title=row.title or row.section_id,
                    order=row.section_order or 0,
                    text=text,
                ))
        return sections

    async def _load_or_extract_claims(
        self, sections: list[_SectionInfo], llm_client
    ) -> dict[str, list[str]]:
        section_claims: dict[str, list[str]] = {}
        extractor = RagasExtractor(llm_client=llm_client) if llm_client else None

        for section in sections:
            # Load cached claims from section_claims table
            cached_result = await self.session.execute(
                select(SectionClaimRow)
                .where(
                    SectionClaimRow.tenant_id == self.tenant_id,
                    SectionClaimRow.run_id == self.run_id,
                    SectionClaimRow.section_id == section.section_id,
                )
                .order_by(SectionClaimRow.claim_index)
            )
            cached_rows = list(cached_result.scalars().all())

            if cached_rows:
                section_claims[section.section_id] = [r.claim_text for r in cached_rows]
            elif extractor is not None:
                snippets = await self._load_section_snippets(section.section_id)
                snippet_texts = [s["text"] for s in snippets]
                fresh = await extractor.extract(section.text, snippet_texts)
                if fresh:
                    for idx, claim_text in enumerate(fresh):
                        self.session.add(SectionClaimRow(
                            tenant_id=self.tenant_id,
                            run_id=self.run_id,
                            section_id=section.section_id,
                            claim_index=idx,
                            claim_text=claim_text,
                        ))
                    await self.session.flush()
                section_claims[section.section_id] = fresh
            else:
                section_claims[section.section_id] = []

        return section_claims

    async def _load_section_snippets(self, section_id: str) -> list[dict]:
        result = await self.session.execute(
            select(SnippetRow.id, SnippetRow.text)
            .join(SnapshotRow, SnapshotRow.id == SnippetRow.snapshot_id)
            .join(
                SectionEvidenceRow,
                (SectionEvidenceRow.snippet_id == SnippetRow.id)
                & (SectionEvidenceRow.tenant_id == SnippetRow.tenant_id),
            )
            .where(
                SectionEvidenceRow.tenant_id == self.tenant_id,
                SectionEvidenceRow.run_id == self.run_id,
                SectionEvidenceRow.section_id == section_id,
            )
        )
        rows = result.all()
        seen: set[str] = set()
        snippets: list[dict] = []
        for row in rows:
            sid = str(row.id)
            if sid not in seen:
                seen.add(sid)
                snippets.append({"snippet_id": sid, "text": (row.text or "")[:600]})
        return snippets

    async def _write_metric(self, name: str, value: int | str | None) -> None:
        result = await self.session.execute(
            select(RunUsageMetricRow).where(
                RunUsageMetricRow.tenant_id == self.tenant_id,
                RunUsageMetricRow.run_id == self.run_id,
                RunUsageMetricRow.metric_name == name,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            if isinstance(value, int) and not isinstance(value, bool):
                existing.metric_number = value
                existing.metric_text = None
            else:
                existing.metric_text = str(value) if value is not None else None
                existing.metric_number = None
            return

        row = RunUsageMetricRow(
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            metric_name=name,
        )
        if isinstance(value, int) and not isinstance(value, bool):
            row.metric_number = value
        else:
            row.metric_text = str(value) if value is not None else None
        self.session.add(row)
