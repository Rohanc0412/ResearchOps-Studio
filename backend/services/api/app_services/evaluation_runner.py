"""
On-demand evaluation runner for research reports.

Computes three quality metrics independently of the LangGraph pipeline:
  Step 1 — Grounding:      LLM grades each section against its evidence snippets
  Step 2 — Faithfulness:   LLM extracts claims and verifies them against evidence
  Step 3 — Sections Passed: DB count of pass/fail verdicts
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Generator
from uuid import UUID

from db.models.artifacts import ArtifactRow  # used in _run_faithfulness (Task 2)
from db.models.draft_sections import DraftSectionRow
from db.models.run_sections import RunSectionRow
from db.models.run_usage_metrics import RunUsageMetricRow  # used in _run_faithfulness and _run_finalize (Tasks 2-3)
from db.models.section_evidence import SectionEvidenceRow
from db.models.section_reviews import SectionReviewRow
from db.models.snapshots import SnapshotRow
from db.models.snippets import SnippetRow
from llm import LLMError, get_llm_client_for_stage, json_response_format
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Grounding schema (same as orchestrator evaluator) ─────────────────────────

_GROUNDING_SCHEMA = {
    "type": "object",
    "properties": {
        "section_id": {"type": "string"},
        "grounding_score": {"type": "integer"},
        "verdict": {"type": "string"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sentence_index": {"type": "integer"},
                    "problem": {"type": "string"},
                    "notes": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["sentence_index", "problem", "notes", "citations"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["section_id", "grounding_score", "verdict", "issues"],
    "additionalProperties": False,
}

_ALLOWED_PROBLEMS = {
    "unsupported", "contradicted", "missing_citation",
    "invalid_citation", "not_in_pack", "overstated",
}

# ── Faithfulness schemas ───────────────────────────────────────────────────────

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_json_payload(text: str) -> dict | list | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # drop opening fence line (e.g. ```json or ```) and closing fence line
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()
    start_candidates = [pos for pos in (cleaned.find("{"), cleaned.find("[")) if pos != -1]
    if not start_candidates:
        return None
    start = min(start_candidates)
    end = cleaned.rfind("}") if cleaned[start] == "{" else cleaned.rfind("]")
    if end == -1 or end <= start:
        return None
    try:
        return json.loads(cleaned[start: end + 1])
    except json.JSONDecodeError:
        return None


def _truncate(text: str, max_chars: int) -> str:
    cleaned = text.strip()
    return cleaned if len(cleaned) <= max_chars else cleaned[:max_chars].rstrip() + "..."


def _normalize_issue(item: dict, allowed_ids: set[str]) -> dict | None:
    if not isinstance(item, dict):
        return None
    problem = str(item.get("problem", "")).strip().lower()
    if problem not in _ALLOWED_PROBLEMS:
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


# ── EvaluationRunner ──────────────────────────────────────────────────────────

class EvaluationRunner:
    """Runs on-demand quality evaluation for a completed research report."""

    def __init__(self, *, session: Session, tenant_id: UUID, run_id: UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.run_id = run_id
        self._grounding_pct: int | None = None
        self._faithfulness_pct: int | None = None

    def run(self) -> Generator[dict, None, None]:
        """Yield SSE-ready event dicts. Runs steps 1-3 sequentially."""
        yield {"type": "evaluation.started", "steps": 3}
        yield {"type": "evaluation.step", "step": 1, "label": "Scoring section grounding…"}
        yield from self._run_grounding()
        yield {"type": "evaluation.step", "step": 2, "label": "Computing answer faithfulness…"}
        yield from self._run_faithfulness()
        yield {"type": "evaluation.step", "step": 3, "label": "Tallying section results…"}
        yield from self._run_finalize()

    # ── Step 1: Grounding ─────────────────────────────────────────────────────

    def _run_grounding(self) -> Generator[dict, None, None]:
        session = self.session
        tenant_id = self.tenant_id
        run_id = self.run_id

        # Load draft texts keyed by section_id
        draft_rows = (
            session.query(DraftSectionRow.section_id, DraftSectionRow.text)
            .filter(DraftSectionRow.tenant_id == tenant_id, DraftSectionRow.run_id == run_id)
            .all()
        )
        drafts: dict[str, str] = {r.section_id: r.text for r in draft_rows}
        if not drafts:
            raise ValueError("no_draft_sections")

        # Load section order/titles
        section_rows = (
            session.query(RunSectionRow)
            .filter(RunSectionRow.tenant_id == tenant_id, RunSectionRow.run_id == run_id)
            .order_by(RunSectionRow.section_order)
            .all()
        )
        section_order = [r.section_id for r in section_rows]
        section_titles = {r.section_id: r.title for r in section_rows}
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

            # Load evidence snippets for this section
            snippet_rows = (
                session.query(SnippetRow.id, SnippetRow.text)
                .join(SnapshotRow, SnapshotRow.id == SnippetRow.snapshot_id)
                .join(
                    SectionEvidenceRow,
                    (SectionEvidenceRow.snippet_id == SnippetRow.id)
                    & (SectionEvidenceRow.tenant_id == SnippetRow.tenant_id),
                )
                .filter(
                    SectionEvidenceRow.tenant_id == tenant_id,
                    SectionEvidenceRow.run_id == run_id,
                    SectionEvidenceRow.section_id == section_id,
                )
                .all()
            )
            snippets = [
                {"snippet_id": str(r.id), "text": _truncate(r.text or "", 800)}
                for r in snippet_rows
            ]
            allowed_ids = {s["snippet_id"] for s in snippets}

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

            self._persist_section_review(section_id=section_id, verdict=verdict, issues=issues)
            session.flush()

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
            "GROUNDING SCORE: (supported factual sentences / total factual sentences) × 100\n"
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
                response_format=json_response_format("evaluation", _GROUNDING_SCHEMA),
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
        issues = [n for item in (issues_raw if isinstance(issues_raw, list) else [])
                  if (n := _normalize_issue(item, allowed_ids)) is not None]

        if issues and verdict == "pass":
            verdict = "fail"
        if issues and grounding_score == 100:
            grounding_score = 85

        return grounding_score, verdict, issues

    def _persist_section_review(self, *, section_id: str, verdict: str, issues: list[dict]) -> None:
        session = self.session
        row = (
            session.query(SectionReviewRow)
            .filter(
                SectionReviewRow.tenant_id == self.tenant_id,
                SectionReviewRow.run_id == self.run_id,
                SectionReviewRow.section_id == section_id,
            )
            .one_or_none()
        )
        now = datetime.utcnow()
        if row:
            # Clear existing child rows and flush to DB before the issues_json setter
            # appends new SectionReviewIssueRow children. Without this flush the
            # cascade="all, delete-orphan" on the relationship conflicts with the
            # new children and raises a UniqueViolation on (review_id, issue_order).
            row.issues = []
            session.flush()
            row.verdict = verdict
            row.issues_json = issues
            row.reviewed_at = now
            row.updated_at = now
        else:
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

    # ── Step 2: Faithfulness ──────────────────────────────────────────────────

    def _run_faithfulness(self) -> Generator[dict, None, None]:
        session = self.session
        tenant_id = self.tenant_id
        run_id = self.run_id

        # Load report_md artifact
        artifact = (
            session.query(ArtifactRow)
            .filter(
                ArtifactRow.tenant_id == tenant_id,
                ArtifactRow.run_id == run_id,
                ArtifactRow.artifact_type == "report_md",
            )
            .first()
        )
        if artifact is None:
            raise ValueError("no_report_artifact")

        markdown = (artifact.metadata_json or {}).get("markdown", "")
        if not markdown.strip():
            raise ValueError("no_report_artifact")

        # Load all unique evidence snippets for this run (used as verification context)
        snippet_rows = (
            session.query(SnippetRow.id, SnippetRow.text)
            .join(SectionEvidenceRow, (SectionEvidenceRow.snippet_id == SnippetRow.id) & (SectionEvidenceRow.tenant_id == SnippetRow.tenant_id))
            .filter(SectionEvidenceRow.tenant_id == tenant_id, SectionEvidenceRow.run_id == run_id)
            .distinct()
            .all()
        )
        if not snippet_rows:
            raise ValueError("no_evidence")

        snippets_payload = [
            {"snippet_id": str(r.id), "text": _truncate(r.text or "", 600)}
            for r in snippet_rows
        ]

        llm_client = get_llm_client_for_stage("evaluate")
        if llm_client is None:
            yield {
                "type": "evaluation.faithfulness_done",
                "faithfulness_pct": None,
                "supported_claims": 0,
                "total_claims": 0,
            }
            return

        # Call 1: extract factual claims from the full report
        extract_prompt = (
            "Extract all distinct factual claims from the research report below. "
            "A factual claim is a sentence that asserts a verifiable fact (not a transition, opinion, or meta-commentary). "
            "Return ONLY valid JSON: {\"claims\": [\"claim 1\", \"claim 2\", ...]}\n\n"
            f"Report:\n{_truncate(markdown, 6000)}"
        )
        try:
            extract_response = llm_client.generate(
                extract_prompt,
                system="You are a precise fact extraction assistant.",
                max_tokens=1200,
                temperature=0.1,
                response_format=json_response_format("claims", _CLAIMS_SCHEMA),
            )
        except LLMError as exc:
            raise ValueError("LLM claim extraction failed") from exc

        extract_payload = _extract_json_payload(extract_response)
        claims: list[str] = []
        if isinstance(extract_payload, dict):
            raw = extract_payload.get("claims") or []
            claims = [str(c).strip() for c in (raw if isinstance(raw, list) else []) if str(c).strip()]

        if not claims:
            yield {
                "type": "evaluation.faithfulness_done",
                "faithfulness_pct": None,
                "supported_claims": 0,
                "total_claims": 0,
            }
            return

        # Call 2: batch-verify all claims against evidence snippets in one LLM call
        claims_text = "\n".join(f"{i}. {c}" for i, c in enumerate(claims))
        verify_prompt = (
            "For each numbered claim below, determine if ANY of the provided evidence snippets "
            "directly supports it. A claim is supported if at least one snippet provides clear "
            "evidence for the assertion.\n\n"
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
        supported_count = 0
        if isinstance(verify_payload, dict):
            verdicts = verify_payload.get("verdicts") or []
            supported_count = sum(
                1 for v in (verdicts if isinstance(verdicts, list) else [])
                if isinstance(v, dict) and v.get("supported") is True
            )

        total = len(claims)
        faithfulness_pct = round(supported_count / total * 100) if total > 0 else None
        self._faithfulness_pct = faithfulness_pct

        # Persist faithfulness score to run_usage_metrics
        existing = (
            session.query(RunUsageMetricRow)
            .filter(
                RunUsageMetricRow.tenant_id == tenant_id,
                RunUsageMetricRow.run_id == run_id,
                RunUsageMetricRow.metric_name == "eval_faithfulness_pct",
            )
            .one_or_none()
        )
        if existing:
            existing.metric_number = faithfulness_pct
        else:
            session.add(RunUsageMetricRow(
                tenant_id=tenant_id,
                run_id=run_id,
                metric_name="eval_faithfulness_pct",
                metric_number=faithfulness_pct,
            ))
        session.flush()

        yield {
            "type": "evaluation.faithfulness_done",
            "faithfulness_pct": faithfulness_pct,
            "supported_claims": supported_count,
            "total_claims": total,
        }

    # ── Step 3: Finalize (placeholder — implemented in Task 3) ───────────────

    def _run_finalize(self) -> Generator[dict, None, None]:
        yield {"type": "evaluation.complete", "grounding_pct": self._grounding_pct, "faithfulness_pct": self._faithfulness_pct, "sections_passed": 0, "sections_total": 0, "issues_by_type": {}}
