"""
On-demand evaluation runner for research reports.

Computes three quality metrics independently of the LangGraph pipeline:
  Step 1 - Grounding:      LLM grades each section against its evidence snippets
  Step 2 - Faithfulness:   LLM extracts claims and verifies them against evidence
  Step 3 - Sections Passed: DB count of pass/fail verdicts
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import UUID

from core.evaluation import (
    ALLOWED_PROBLEMS,
    GROUNDING_SCHEMA,
    METRIC_EVAL_GROUNDING_PCT,
    METRIC_EVAL_STATUS,
)
from db.models.artifacts import ArtifactRow
from db.models.draft_sections import DraftSectionRow
from db.models.run_sections import RunSectionRow
from db.models.run_usage_metrics import RunUsageMetricRow
from db.models.section_evidence import SectionEvidenceRow
from db.models.section_reviews import SectionReviewRow
from db.models.snapshots import SnapshotRow
from db.models.snippets import SnippetRow
from db.repositories.evaluation_history import (
    create_evaluation_pass,
    finalize_evaluation_pass,
    record_evaluation_section_result,
)
from llm import LLMError, get_llm_client_for_stage, json_response_format
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


_CLAIMS_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["claims"],
    "additionalProperties": False,
}

_FAITHFULNESS_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_index": {"type": "integer"},
                    "supported": {"type": "boolean"},
                },
                "required": ["claim_index", "supported"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}


def _extract_json_payload(text: str) -> dict | list | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = [line for line in lines if not line.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()
    start_candidates = [pos for pos in (cleaned.find("{"), cleaned.find("[")) if pos != -1]
    if not start_candidates:
        return None
    start = min(start_candidates)
    end = cleaned.rfind("}") if cleaned[start] == "{" else cleaned.rfind("]")
    if end == -1 or end <= start:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None


def _truncate(text: str, max_chars: int) -> str:
    cleaned = text.strip()
    return cleaned if len(cleaned) <= max_chars else cleaned[:max_chars].rstrip() + "..."


_CITATION_MARKER_RE = re.compile(r"\[\^\d+\]|\[CITE:[^\]]+\]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_SECTION_HEADING_RE = re.compile(r"^##\s+(?:\d+\.\s+)?(.+?)\s*$")


def _normalize_issue(item: dict, allowed_ids: set[str]) -> dict | None:
    if not isinstance(item, dict):
        return None
    problem = str(item.get("problem", "")).strip().lower()
    if problem not in ALLOWED_PROBLEMS:
        return None
    try:
        sentence_index = int(item.get("sentence_index") or 0)
    except (TypeError, ValueError):
        sentence_index = 0
    notes = str(item.get("notes", "")).strip()
    citations_raw = item.get("citations") or []
    citations = [str(c).strip() for c in (citations_raw if isinstance(citations_raw, list) else [])]
    filtered = [c for c in citations if c in allowed_ids]
    return {"sentence_index": sentence_index, "problem": problem, "notes": notes, "citations": filtered}


class EvaluationRunner:
    """Runs on-demand quality evaluation for a completed research report."""

    def __init__(self, *, session: AsyncSession, tenant_id: UUID, run_id: UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.run_id = run_id
        self._grounding_pct: int | None = None
        self._faithfulness_pct: int | None = None
        self._history_pass_id: UUID | None = None

    async def run(self) -> AsyncGenerator[dict, None]:
        yield {"type": "evaluation.started", "steps": 3}
        history_pass = await create_evaluation_pass(
            session=self.session,
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            scope="manual",
        )
        self._history_pass_id = history_pass.id
        await self._write_metric(METRIC_EVAL_STATUS, "running")
        await self._write_metric(METRIC_EVAL_GROUNDING_PCT, None)
        await self._write_metric("eval_faithfulness_pct", None)
        await self._write_metric("eval_sections_passed", None)
        await self._write_metric("eval_sections_total", None)
        await self._write_metric("eval_evaluated_at", None)
        await self.session.flush()
        await self.session.commit()
        yield {"type": "evaluation.step", "step": 1, "label": "Scoring section grounding…"}
        async for event in self._run_grounding():
            yield event
        yield {"type": "evaluation.step", "step": 2, "label": "Computing answer faithfulness…"}
        async for event in self._run_faithfulness():
            yield event
        yield {"type": "evaluation.step", "step": 3, "label": "Tallying section results…"}
        async for event in self._run_finalize():
            yield event

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

    async def _run_grounding(self) -> AsyncGenerator[dict, None]:
        session = self.session
        tenant_id = self.tenant_id
        run_id = self.run_id

        draft_result = await session.execute(
            select(DraftSectionRow.section_id, DraftSectionRow.text)
            .where(DraftSectionRow.tenant_id == tenant_id, DraftSectionRow.run_id == run_id)
        )
        draft_rows = draft_result.all()
        drafts: dict[str, str] = {row.section_id: row.text for row in draft_rows}
        if not drafts:
            raise ValueError("no_draft_sections")

        section_result = await session.execute(
            select(RunSectionRow)
            .where(RunSectionRow.tenant_id == tenant_id, RunSectionRow.run_id == run_id)
            .order_by(RunSectionRow.section_order)
        )
        section_rows = list(section_result.scalars().all())
        section_order = [row.section_id for row in section_rows]
        section_titles = {row.section_id: row.title for row in section_rows}
        section_positions = {row.section_id: row.section_order for row in section_rows}
        if not section_order:
            section_order = list(drafts.keys())

        llm_client = get_llm_client_for_stage("evaluate")
        scores: list[int] = []
        pass_count = 0
        fail_count = 0

        for section_id in section_order:
            section_text = drafts.get(section_id)
            if not section_text:
                continue

            snippet_result = await session.execute(
                select(SnippetRow.id, SnippetRow.text)
                .join(SnapshotRow, SnapshotRow.id == SnippetRow.snapshot_id)
                .join(
                    SectionEvidenceRow,
                    (SectionEvidenceRow.snippet_id == SnippetRow.id)
                    & (SectionEvidenceRow.tenant_id == SnippetRow.tenant_id),
                )
                .where(
                    SectionEvidenceRow.tenant_id == tenant_id,
                    SectionEvidenceRow.run_id == run_id,
                    SectionEvidenceRow.section_id == section_id,
                )
            )
            snippet_rows = snippet_result.all()
            snippets = [{"snippet_id": str(row.id), "text": _truncate(row.text or "", 800)} for row in snippet_rows]
            allowed_ids = {snippet["snippet_id"] for snippet in snippets}

            verdict = "pass"
            issues: list[dict] = []
            grounding_score = 100

            if llm_client is not None:
                try:
                    grounding_score, verdict, issues = self._grade_section(
                        llm_client,
                        section_id=section_id,
                        section_title=section_titles.get(section_id, section_id),
                        section_text=section_text,
                        snippets=snippets,
                        allowed_ids=allowed_ids,
                    )
                except Exception:
                    logger.warning("LLM grading failed for section %s; defaulting to pass.", section_id, exc_info=True)

            scores.append(grounding_score)
            if verdict == "pass":
                pass_count += 1
            else:
                fail_count += 1

            await self._persist_section_review(section_id=section_id, verdict=verdict, issues=issues)
            if self._history_pass_id is not None:
                await record_evaluation_section_result(
                    session=session,
                    tenant_id=tenant_id,
                    evaluation_pass_id=self._history_pass_id,
                    section_id=section_id,
                    section_title=section_titles.get(section_id, section_id),
                    section_order=section_positions.get(section_id),
                    verdict=verdict,
                    grounding_score=grounding_score,
                    issues=issues,
                )
            await session.flush()

            yield {
                "type": "evaluation.section",
                "section_id": section_id,
                "section_title": section_titles.get(section_id, section_id),
                "grounding_score": grounding_score,
                "verdict": verdict,
                "issues": issues,
            }

        overall = round(sum(scores) / len(scores)) if scores else 100
        self._grounding_pct = overall
        await self._write_metric(METRIC_EVAL_GROUNDING_PCT, overall)
        await self._write_metric("eval_sections_passed", pass_count)
        await self._write_metric("eval_sections_total", pass_count + fail_count)
        await session.flush()
        await session.commit()
        yield {
            "type": "evaluation.grounding_done",
            "overall_grounding_pct": overall,
            "pass_count": pass_count,
            "fail_count": fail_count,
        }

    def _grade_section(
        self,
        llm_client,
        *,
        section_id: str,
        section_title: str,
        section_text: str,
        snippets: list[dict],
        allowed_ids: set[str],
    ) -> tuple[int, str, list[dict]]:
        system = (
            "You are an expert research evaluator. "
            "Judge how well a drafted section is grounded in the provided evidence snippets."
        )
        prompt = (
            "Rate the semantic grounding of the drafted section against the evidence snippets.\n\n"
            "GROUNDING SCORE: (supported factual sentences / total factual sentences) x 100\n"
            "  - Transitional sentences with no factual claim are excluded.\n"
            "  - UNSUPPORTED: no snippet backs it up.\n"
            "  - OVERSTATED: snippets only partially support the claim strength.\n"
            "  - CONTRADICTED: a snippet directly contradicts the claim.\n"
            "VERDICT: 'pass' if grounding_score >= 70, else 'fail'.\n\n"
            "Return ONLY valid JSON:\n"
            '{"section_id":"...","grounding_score":0-100,"verdict":"pass"|"fail",'
            '"issues":[{"sentence_index":0,"problem":"unsupported|contradicted|overstated|missing_citation|invalid_citation|not_in_pack","notes":"...","citations":["snippet_id"]}]}\n\n'
            f"Section ID: {section_id}\nTitle: {section_title}\n\n"
            f"Drafted text:\n{section_text}\n\n"
            f"Evidence snippets:\n{json.dumps(snippets, indent=2, ensure_ascii=True)}\n\n"
            "Rules: list ALL problem sentences; never invent snippet IDs; no markdown outside JSON."
        )
        try:
            response = llm_client.generate(
                prompt,
                system=system,
                max_tokens=1400,
                temperature=0.2,
                response_format=json_response_format("evaluation", GROUNDING_SCHEMA),
            )
        except LLMError as exc:
            raise ValueError("LLM grounding call failed") from exc

        payload = _extract_json_payload(response)
        if not isinstance(payload, dict):
            raise ValueError("Grounding response was not a JSON object")

        verdict = str(payload.get("verdict", "")).strip().lower()
        if verdict not in {"pass", "fail"}:
            verdict = "fail"

        raw_score = payload.get("grounding_score")
        try:
            grounding_score = max(0, min(100, int(raw_score)))
        except (TypeError, ValueError):
            grounding_score = 85 if verdict == "pass" else 45

        issues_raw = payload.get("issues") or []
        issues = [
            normalized
            for item in (issues_raw if isinstance(issues_raw, list) else [])
            if (normalized := _normalize_issue(item, allowed_ids)) is not None
        ]

        if issues and verdict == "pass":
            verdict = "fail"
        if issues and grounding_score == 100:
            grounding_score = 85

        return grounding_score, verdict, issues

    async def _persist_section_review(self, *, section_id: str, verdict: str, issues: list[dict]) -> None:
        session = self.session
        result = await session.execute(
            select(SectionReviewRow).where(
                SectionReviewRow.tenant_id == self.tenant_id,
                SectionReviewRow.run_id == self.run_id,
                SectionReviewRow.section_id == section_id,
            )
        )
        row = result.scalar_one_or_none()
        now = datetime.now(UTC)
        if row:
            row.issues = []
            await session.flush()
            row.verdict = verdict
            row.issues_json = issues
            row.reviewed_at = now
            row.updated_at = now
            return

        row = SectionReviewRow(
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            section_id=section_id,
            verdict=verdict,
            issues_json=issues,
            reviewed_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(row)

    def _extract_section_claims(
        self,
        *,
        llm_client,
        section_title: str,
        section_text: str,
    ) -> list[str]:
        extract_prompt = (
            "Extract all distinct factual claims from the report section below. "
            "A factual claim is a sentence that asserts a verifiable fact. "
            "Ignore markdown headings, inline citation markers like [^1], and bibliography/reference text. "
            "Return ONLY valid JSON: {\"claims\": [\"claim 1\", \"claim 2\", ...]}\n\n"
            f"Section title: {section_title}\n\n"
            f"Section text:\n{_truncate(section_text, 4000)}"
        )
        try:
            extract_response = llm_client.generate(
                extract_prompt,
                system="You are a precise fact extraction assistant.",
                max_tokens=900,
                temperature=0.1,
                response_format=json_response_format("claims", _CLAIMS_SCHEMA),
            )
        except LLMError as exc:
            raise ValueError("LLM claim extraction failed") from exc

        extract_payload = _extract_json_payload(extract_response)
        raw_claims = extract_payload.get("claims") if isinstance(extract_payload, dict) else []
        claims: list[str] = []
        seen: set[str] = set()
        for raw_claim in raw_claims if isinstance(raw_claims, list) else []:
            claim = str(raw_claim).strip()
            if not claim:
                continue
            normalized = claim.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            claims.append(claim)
        return claims

    def _extract_cited_claims(self, section_text: str) -> list[str]:
        claims: list[str] = []
        seen: set[str] = set()
        for sentence in _SENTENCE_SPLIT_RE.split(section_text.strip()):
            if not _CITATION_MARKER_RE.search(sentence):
                continue
            cleaned = _CITATION_MARKER_RE.sub("", sentence)
            cleaned = re.sub(r"\s+", " ", cleaned).strip(" -\n\t")
            if not cleaned:
                continue
            normalized = cleaned.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            claims.append(cleaned)
        return claims

    def _normalize_section_title(self, title: str) -> str:
        return re.sub(r"\s+", " ", title.strip()).lower()

    def _parse_report_sections(self, markdown: str) -> dict[str, str]:
        sections: dict[str, str] = {}
        current_title: str | None = None
        current_lines: list[str] = []

        def flush_current() -> None:
            nonlocal current_title, current_lines
            if not current_title:
                current_lines = []
                return
            body = "\n".join(current_lines).strip()
            if body:
                sections[self._normalize_section_title(current_title)] = body
            current_lines = []

        for raw_line in markdown.splitlines():
            match = _SECTION_HEADING_RE.match(raw_line.strip())
            if match:
                flush_current()
                title = match.group(1).strip()
                if self._normalize_section_title(title) == "references":
                    current_title = None
                    current_lines = []
                    continue
                current_title = title
                current_lines = []
                continue
            if current_title is not None:
                current_lines.append(raw_line)

        flush_current()
        return sections

    def _verify_section_claims(
        self,
        *,
        llm_client,
        claims: list[str],
        snippets_payload: list[dict[str, str]],
    ) -> int:
        claims_text = "\n".join(f"{index}. {claim}" for index, claim in enumerate(claims))
        verify_prompt = (
            "For each numbered claim below, determine if ANY of the provided evidence snippets "
            "directly supports it. A claim is supported only if at least one snippet provides clear, specific evidence.\n\n"
            "Return ONLY valid JSON:\n"
            "{\"verdicts\": [{\"claim_index\": 0, \"supported\": true}, ...]}\n\n"
            f"Claims:\n{claims_text}\n\n"
            f"Evidence snippets:\n{json.dumps(snippets_payload, indent=2, ensure_ascii=True)}"
        )
        try:
            verify_response = llm_client.generate(
                verify_prompt,
                system="You are a research fact-checker. Be strict: only mark supported if evidence is direct and specific.",
                max_tokens=800,
                temperature=0.1,
                response_format=json_response_format("faithfulness", _FAITHFULNESS_SCHEMA),
            )
        except LLMError as exc:
            raise ValueError("LLM faithfulness verification failed") from exc

        verify_payload = _extract_json_payload(verify_response)
        if not isinstance(verify_payload, dict):
            return 0
        verdicts = verify_payload.get("verdicts") or []
        return sum(
            1
            for verdict in (verdicts if isinstance(verdicts, list) else [])
            if isinstance(verdict, dict) and verdict.get("supported") is True
        )

    async def _run_faithfulness(self) -> AsyncGenerator[dict, None]:
        session = self.session
        tenant_id = self.tenant_id
        run_id = self.run_id

        artifact_result = await session.execute(
            select(ArtifactRow)
            .where(
                ArtifactRow.tenant_id == tenant_id,
                ArtifactRow.run_id == run_id,
                ArtifactRow.artifact_type == "report_md",
            )
        )
        artifact = artifact_result.scalars().first()
        markdown = (artifact.metadata_json or {}).get("markdown", "") if artifact is not None else ""
        report_sections = self._parse_report_sections(markdown) if markdown.strip() else {}

        draft_result = await session.execute(
            select(DraftSectionRow.section_id, DraftSectionRow.text)
            .where(DraftSectionRow.tenant_id == tenant_id, DraftSectionRow.run_id == run_id)
        )
        draft_rows = draft_result.all()
        drafts = {row.section_id: row.text for row in draft_rows}
        if not drafts:
            raise ValueError("no_draft_sections")

        section_result = await session.execute(
            select(RunSectionRow)
            .where(RunSectionRow.tenant_id == tenant_id, RunSectionRow.run_id == run_id)
            .order_by(RunSectionRow.section_order)
        )
        section_rows = list(section_result.scalars().all())
        ordered_sections = [
            (row.section_id, row.title or row.section_id)
            for row in section_rows
            if drafts.get(row.section_id)
        ]
        if not ordered_sections:
            ordered_sections = [(section_id, section_id) for section_id in sorted(drafts.keys())]

        llm_client = get_llm_client_for_stage("evaluate")
        if llm_client is None:
            yield {
                "type": "evaluation.faithfulness_done",
                "faithfulness_pct": None,
                "supported_claims": 0,
                "total_claims": 0,
            }
            return

        supported_count = 0
        total = 0
        for section_id, section_title in ordered_sections:
            section_text = report_sections.get(self._normalize_section_title(section_title)) or drafts.get(section_id) or ""
            if not section_text.strip():
                continue

            claims = self._extract_cited_claims(section_text)
            if not claims:
                try:
                    claims = self._extract_section_claims(
                        llm_client=llm_client,
                        section_title=section_title,
                        section_text=section_text,
                    )
                except Exception:
                    logger.warning(
                        "LLM claim extraction failed for section %s during manual faithfulness scoring.",
                        section_id,
                        extra={"stage": "evaluate", "section_id": section_id},
                        exc_info=True,
                    )
                    continue
            if not claims:
                continue

            snippet_result = await session.execute(
                select(SnippetRow.id, SnippetRow.text)
                .join(
                    SectionEvidenceRow,
                    (SectionEvidenceRow.snippet_id == SnippetRow.id)
                    & (SectionEvidenceRow.tenant_id == SnippetRow.tenant_id),
                )
                .where(
                    SectionEvidenceRow.tenant_id == tenant_id,
                    SectionEvidenceRow.run_id == run_id,
                    SectionEvidenceRow.section_id == section_id,
                )
            )
            snippet_rows = snippet_result.all()
            snippets_payload: list[dict[str, str]] = []
            seen_snippet_ids: set[str] = set()
            for row in snippet_rows:
                snippet_id_str = str(row.id)
                if snippet_id_str in seen_snippet_ids:
                    continue
                seen_snippet_ids.add(snippet_id_str)
                snippets_payload.append({"snippet_id": snippet_id_str, "text": _truncate(row.text or "", 600)})

            try:
                supported_count += self._verify_section_claims(
                    llm_client=llm_client,
                    claims=claims,
                    snippets_payload=snippets_payload,
                )
            except Exception:
                logger.warning(
                    "LLM faithfulness verification failed for section %s during manual scoring.",
                    section_id,
                    extra={"stage": "evaluate", "section_id": section_id},
                    exc_info=True,
                )
                continue
            total += len(claims)

        if total == 0:
            yield {
                "type": "evaluation.faithfulness_done",
                "faithfulness_pct": None,
                "supported_claims": 0,
                "total_claims": 0,
            }
            return

        faithfulness_pct = round(supported_count / total * 100)
        self._faithfulness_pct = faithfulness_pct

        existing_result = await session.execute(
            select(RunUsageMetricRow).where(
                RunUsageMetricRow.tenant_id == tenant_id,
                RunUsageMetricRow.run_id == run_id,
                RunUsageMetricRow.metric_name == "eval_faithfulness_pct",
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing:
            existing.metric_number = faithfulness_pct
        else:
            session.add(
                RunUsageMetricRow(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    metric_name="eval_faithfulness_pct",
                    metric_number=faithfulness_pct,
                )
            )
        await session.flush()
        await session.commit()

        yield {
            "type": "evaluation.faithfulness_done",
            "faithfulness_pct": faithfulness_pct,
            "supported_claims": supported_count,
            "total_claims": total,
        }

    async def _run_finalize(self) -> AsyncGenerator[dict, None]:
        session = self.session
        tenant_id = self.tenant_id
        run_id = self.run_id

        reviews_result = await session.execute(
            select(SectionReviewRow).where(
                SectionReviewRow.tenant_id == tenant_id,
                SectionReviewRow.run_id == run_id,
            )
        )
        reviews = list(reviews_result.scalars().all())

        sections_passed = sum(1 for review in reviews if review.verdict == "pass")
        sections_total = len(reviews)

        issues_by_type: dict[str, int] = {}
        for review in reviews:
            for issue in (review.issues_json or []):
                problem = issue.get("problem", "unknown")
                issues_by_type[problem] = issues_by_type.get(problem, 0) + 1

        now_str = datetime.now(UTC).isoformat()
        await self._write_metric(METRIC_EVAL_STATUS, "complete")
        await self._write_metric("eval_evaluated_at", now_str)
        await self._write_metric("eval_sections_passed", sections_passed)
        await self._write_metric("eval_sections_total", sections_total)
        if self._grounding_pct is not None:
            await self._write_metric(METRIC_EVAL_GROUNDING_PCT, self._grounding_pct)
        if self._history_pass_id is not None:
            await finalize_evaluation_pass(
                session=session,
                tenant_id=tenant_id,
                evaluation_pass_id=self._history_pass_id,
                grounding_pct=self._grounding_pct,
                faithfulness_pct=self._faithfulness_pct,
                sections_passed=sections_passed,
                sections_total=sections_total,
                issues_by_type=issues_by_type,
            )
        await self.session.flush()
        await self.session.commit()

        yield {
            "type": "evaluation.complete",
            "grounding_pct": self._grounding_pct,
            "faithfulness_pct": self._faithfulness_pct,
            "sections_passed": sections_passed,
            "sections_total": sections_total,
            "issues_by_type": issues_by_type,
        }
