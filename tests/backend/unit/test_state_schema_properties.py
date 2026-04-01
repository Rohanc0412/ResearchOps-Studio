"""
Property-based tests for OrchestratorState and nested Pydantic models.

Uses Hypothesis to generate varied inputs and verify:
- JSON serialisation round-trips are lossless
- Constraint invariants hold (confidence ∈ [0,1], counters ≥ 0, etc.)
- All enum values are accepted
- Optional fields are handled correctly in nested structures
- Model rejection of invalid inputs stays stable
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from core.orchestrator.state import (
    Claim,
    EvaluatorDecision,
    EvidenceSnippetRef,
    FactCheckResult,
    FactCheckStatus,
    OrchestratorState,
    OutlineModel,
    OutlineSection,
    RepairPlan,
    SourceRef,
    ValidationError as StateValidationError,
    ValidationErrorType,
)

# ── Shared strategies ─────────────────────────────────────────────────────────

_uuids = st.uuids()
_nonempty_text = st.text(min_size=1, max_size=200).filter(lambda s: s.strip())
_maybe_text = st.one_of(st.none(), st.text(max_size=200))
_unit_float = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
_small_int = st.integers(min_value=0, max_value=100)


@st.composite
def source_refs(draw) -> SourceRef:
    return SourceRef(
        source_id=draw(_uuids),
        canonical_id=draw(_nonempty_text),
        title=draw(_nonempty_text),
        authors=draw(st.lists(st.text(max_size=100), max_size=5)),
        abstract=draw(_maybe_text),
        year=draw(st.one_of(st.none(), st.integers(min_value=1900, max_value=2100))),
        venue=draw(_maybe_text),
        doi=draw(_maybe_text),
        arxiv_id=draw(_maybe_text),
        url=draw(_maybe_text),
        pdf_url=draw(_maybe_text),
        connector=draw(_nonempty_text),
        origin=draw(_maybe_text),
        cited_by_count=draw(st.one_of(st.none(), st.integers(min_value=0, max_value=100_000))),
        quality_score=draw(_unit_float),
    )


@st.composite
def evidence_snippet_refs(draw) -> EvidenceSnippetRef:
    char_start = draw(st.integers(min_value=0, max_value=10_000))
    char_end = draw(st.integers(min_value=char_start, max_value=char_start + 2000))
    return EvidenceSnippetRef(
        snippet_id=draw(_uuids),
        source_id=draw(_uuids),
        text=draw(st.text(min_size=1, max_size=500)),
        char_start=char_start,
        char_end=char_end,
        embedding_vector=draw(
            st.one_of(
                st.none(),
                st.lists(
                    st.floats(allow_nan=False, allow_infinity=False, min_value=-1.0, max_value=1.0),
                    min_size=3,
                    max_size=16,
                ),
            )
        ),
    )


@st.composite
def outline_sections(draw) -> OutlineSection:
    return OutlineSection(
        section_id=draw(_nonempty_text),
        title=draw(_nonempty_text),
        goal=draw(_nonempty_text),
        key_points=draw(st.lists(st.text(max_size=100), max_size=5)),
        suggested_evidence_themes=draw(st.lists(st.text(max_size=100), max_size=3)),
        section_order=draw(st.integers(min_value=0, max_value=50)),
    )


@st.composite
def claims(draw) -> Claim:
    return Claim(
        claim_id=draw(_nonempty_text),
        text=draw(_nonempty_text),
        section_id=draw(_maybe_text),
        citation_ids=draw(st.lists(st.text(max_size=50), max_size=5)),
        requires_evidence=draw(st.booleans()),
    )


@st.composite
def fact_check_results(draw) -> FactCheckResult:
    return FactCheckResult(
        claim_id=draw(_nonempty_text),
        status=draw(st.sampled_from(FactCheckStatus)),
        supporting_snippets=draw(st.lists(_uuids, max_size=4)),
        contradicting_snippets=draw(st.lists(_uuids, max_size=4)),
        confidence=draw(_unit_float),
        explanation=draw(st.text(max_size=300)),
    )


@st.composite
def validation_errors(draw) -> StateValidationError:
    return StateValidationError(
        error_type=draw(st.sampled_from(ValidationErrorType)),
        claim_id=draw(_maybe_text),
        section_id=draw(_maybe_text),
        citation_id=draw(_maybe_text),
        description=draw(_nonempty_text),
        severity=draw(st.sampled_from(["error", "warning"])),
    )


@st.composite
def orchestrator_states(draw) -> OrchestratorState:
    sections = draw(st.lists(outline_sections(), min_size=0, max_size=4))
    return OrchestratorState(
        tenant_id=draw(_uuids),
        run_id=draw(_uuids),
        project_id=draw(st.one_of(st.none(), _uuids)),
        user_query=draw(_nonempty_text),
        research_goal=draw(_maybe_text),
        retrieved_sources=draw(st.lists(source_refs(), max_size=3)),
        evidence_snippets=draw(st.lists(evidence_snippet_refs(), max_size=3)),
        vetted_sources=draw(st.lists(source_refs(), max_size=2)),
        outline=draw(
            st.one_of(
                st.none(),
                st.builds(OutlineModel, sections=st.just(sections)),
            )
        ),
        draft_text=draw(st.text(max_size=500)),
        draft_version=draw(_small_int),
        extracted_claims=draw(st.lists(claims(), max_size=4)),
        citation_errors=draw(st.lists(validation_errors(), max_size=3)),
        fact_check_results=draw(st.lists(fact_check_results(), max_size=3)),
        repair_plan=draw(
            st.one_of(
                st.none(),
                st.builds(
                    RepairPlan,
                    target_claims=st.lists(st.text(max_size=30), max_size=3),
                    target_sections=st.lists(st.text(max_size=30), max_size=3),
                    strategy=st.text(max_size=100),
                    additional_evidence_needed=st.booleans(),
                ),
            )
        ),
        repair_attempts=draw(_small_int),
        max_repair_attempts=draw(st.integers(min_value=1, max_value=10)),
        evaluator_decision=draw(st.one_of(st.none(), st.sampled_from(EvaluatorDecision))),
        evaluation_reason=draw(st.text(max_size=200)),
        iteration_count=draw(_small_int),
        max_iterations=draw(st.integers(min_value=1, max_value=20)),
    )


# ── SourceRef properties ──────────────────────────────────────────────────────


@given(src=source_refs())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_source_ref_json_round_trip(src: SourceRef) -> None:
    """SourceRef must survive model_dump_json → model_validate_json losslessly."""
    as_json = src.model_dump_json()
    restored = SourceRef.model_validate_json(as_json)
    assert restored == src


@given(src=source_refs())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_source_ref_quality_score_in_range(src: SourceRef) -> None:
    assert 0.0 <= src.quality_score <= 1.0


@given(src=source_refs())
@settings(max_examples=50)
def test_source_ref_dict_is_json_serialisable(src: SourceRef) -> None:
    d = src.model_dump(mode="json")
    # Must be JSON-serialisable without error
    json.dumps(d)


# ── EvidenceSnippetRef properties ─────────────────────────────────────────────


@given(snip=evidence_snippet_refs())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_evidence_snippet_char_end_gte_start(snip: EvidenceSnippetRef) -> None:
    assert snip.char_end >= snip.char_start


@given(snip=evidence_snippet_refs())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_evidence_snippet_round_trip(snip: EvidenceSnippetRef) -> None:
    restored = EvidenceSnippetRef.model_validate_json(snip.model_dump_json())
    assert restored == snip


# ── FactCheckResult properties ────────────────────────────────────────────────


@given(fcr=fact_check_results())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_fact_check_confidence_in_unit_interval(fcr: FactCheckResult) -> None:
    assert 0.0 <= fcr.confidence <= 1.0


@given(fcr=fact_check_results())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_fact_check_status_is_valid_enum(fcr: FactCheckResult) -> None:
    assert fcr.status in FactCheckStatus


@given(fcr=fact_check_results())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_fact_check_round_trip(fcr: FactCheckResult) -> None:
    restored = FactCheckResult.model_validate_json(fcr.model_dump_json())
    assert restored == fcr


# ── All FactCheckStatus values are accepted ────────────────────────────────────


@pytest.mark.parametrize("status", list(FactCheckStatus))
def test_fact_check_all_statuses_accepted(status: FactCheckStatus) -> None:
    fcr = FactCheckResult(claim_id="c1", status=status, confidence=0.5)
    assert fcr.status == status


# ── ValidationError properties ────────────────────────────────────────────────


@given(ve=validation_errors())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_validation_error_round_trip(ve: StateValidationError) -> None:
    restored = StateValidationError.model_validate_json(ve.model_dump_json())
    assert restored == ve


@given(ve=validation_errors())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_validation_error_type_is_valid_enum(ve: StateValidationError) -> None:
    assert ve.error_type in ValidationErrorType


@pytest.mark.parametrize("error_type", list(ValidationErrorType))
def test_validation_error_all_types_accepted(error_type: ValidationErrorType) -> None:
    ve = StateValidationError(error_type=error_type, description="test error")
    assert ve.error_type == error_type


# ── Claim properties ──────────────────────────────────────────────────────────


@given(c=claims())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_claim_round_trip(c: Claim) -> None:
    restored = Claim.model_validate_json(c.model_dump_json())
    assert restored == c


@given(c=claims())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_claim_citation_ids_are_strings(c: Claim) -> None:
    assert all(isinstance(cid, str) for cid in c.citation_ids)


# ── OutlineSection properties ─────────────────────────────────────────────────


@given(sec=outline_sections())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_outline_section_order_non_negative(sec: OutlineSection) -> None:
    assert sec.section_order >= 0


@given(sec=outline_sections())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_outline_section_round_trip(sec: OutlineSection) -> None:
    restored = OutlineSection.model_validate_json(sec.model_dump_json())
    assert restored == sec


# ── EvaluatorDecision enum coverage ───────────────────────────────────────────


@pytest.mark.parametrize("decision", list(EvaluatorDecision))
def test_evaluator_decision_serialises(decision: EvaluatorDecision) -> None:
    state = OrchestratorState(
        tenant_id="00000000-0000-0000-0000-000000000001",
        run_id="00000000-0000-0000-0000-000000000002",
        user_query="query",
        evaluator_decision=decision,
    )
    assert state.evaluator_decision == decision
    restored = OrchestratorState.model_validate_json(state.model_dump_json())
    assert restored.evaluator_decision == decision


# ── OrchestratorState properties ─────────────────────────────────────────────


@given(s=orchestrator_states())
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_orchestrator_state_json_round_trip(s: OrchestratorState) -> None:
    """Full state round-trips through JSON without data loss."""
    as_json = s.model_dump_json()
    restored = OrchestratorState.model_validate_json(as_json)
    assert restored.tenant_id == s.tenant_id
    assert restored.run_id == s.run_id
    assert restored.user_query == s.user_query
    assert len(restored.retrieved_sources) == len(s.retrieved_sources)
    assert len(restored.extracted_claims) == len(s.extracted_claims)
    assert len(restored.fact_check_results) == len(s.fact_check_results)


@given(s=orchestrator_states())
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_orchestrator_state_counters_non_negative(s: OrchestratorState) -> None:
    assert s.draft_version >= 0
    assert s.repair_attempts >= 0
    assert s.iteration_count >= 0


@given(s=orchestrator_states())
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_orchestrator_state_confidence_scores_in_range(s: OrchestratorState) -> None:
    for fcr in s.fact_check_results:
        assert 0.0 <= fcr.confidence <= 1.0
    for src in s.retrieved_sources + s.vetted_sources:
        assert 0.0 <= src.quality_score <= 1.0


@given(s=orchestrator_states())
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_orchestrator_state_dict_is_json_serialisable(s: OrchestratorState) -> None:
    d = s.model_dump(mode="json")
    json.dumps(d)


# ── Rejection of invalid inputs ───────────────────────────────────────────────


def test_fact_check_confidence_above_one_accepted_by_model() -> None:
    """Pydantic does not enforce 0–1 range on float — document this behaviour."""
    # The model currently doesn't validate the range; this test documents the
    # current behaviour so any future constraint is caught as a breaking change.
    fcr = FactCheckResult(claim_id="c1", status=FactCheckStatus.SUPPORTED, confidence=1.5)
    assert fcr.confidence == 1.5  # no validation error — documented gap


def test_orchestrator_state_requires_tenant_and_run_ids() -> None:
    with pytest.raises(ValidationError):
        OrchestratorState(user_query="q")  # type: ignore[call-arg]


def test_orchestrator_state_requires_user_query() -> None:
    with pytest.raises(ValidationError):
        OrchestratorState(  # type: ignore[call-arg]
            tenant_id="00000000-0000-0000-0000-000000000001",
            run_id="00000000-0000-0000-0000-000000000002",
        )
