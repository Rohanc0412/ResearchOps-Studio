from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.contracts.artifacts import ExperimentPlan, LiteratureMap, StructuredReport
from src.contracts.errors import ClaimPolicyViolationError
from src.enforcement.claim_enforcer import ClaimEnforcer, load_system_policy
from src.enforcement.evidence_validator import EvidenceValidator


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_examples_golden(repo_root: Path, evidence_store) -> None:
    policy = load_system_policy(repo_root / "claim_policy.yaml")
    claim_enforcer = ClaimEnforcer(policy)

    valid_report = StructuredReport.model_validate(_load_json(repo_root / "examples" / "valid_report.json"))
    claim_enforcer.enforce_report(valid_report)
    EvidenceValidator.validate_report(valid_report, evidence_store)

    valid_lit = LiteratureMap.model_validate(_load_json(repo_root / "examples" / "valid_literature_map.json"))
    EvidenceValidator.validate_literature_map(valid_lit, evidence_store)

    valid_plan = ExperimentPlan.model_validate(_load_json(repo_root / "examples" / "valid_experiment_plan.json"))
    EvidenceValidator.validate_experiment_plan(valid_plan, evidence_store)

    rejected_report = StructuredReport.model_validate(
        _load_json(repo_root / "examples" / "rejected_report_missing_citations.json")
    )
    with pytest.raises(ClaimPolicyViolationError) as e:
        claim_enforcer.enforce_report(rejected_report)
    assert str(e.value) == "Non-trivial claim requires at least one citation_key: claim_id=claim_intro_1"

