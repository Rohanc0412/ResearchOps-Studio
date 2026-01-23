from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.contracts.artifacts import StructuredReport
from src.contracts.errors import ClaimPolicyViolationError
from src.enforcement.claim_enforcer import ClaimEnforcer, load_system_policy


def test_report_non_trivial_claim_missing_citations_fails_closed(repo_root: Path) -> None:
    policy = load_system_policy(repo_root / "claim_policy.yaml")
    enforcer = ClaimEnforcer(policy)

    data = json.loads(
        (repo_root / "tests" / "golden" / "rejected_report_missing_citations.json").read_text(encoding="utf-8")
    )
    report = StructuredReport.model_validate(data)

    with pytest.raises(ClaimPolicyViolationError) as e:
        enforcer.enforce_report(report)

    assert str(e.value) == "Non-trivial claim requires at least one citation_key: claim_id=claim_intro_1"


def test_report_claim_references_missing_citation_key_fails_closed(repo_root: Path) -> None:
    policy = load_system_policy(repo_root / "claim_policy.yaml")
    enforcer = ClaimEnforcer(policy)

    report_dict = {
        "artifact_type": "structured_report",
        "sections": [
            {
                "name": "intro",
                "text": "t",
                "claims": [
                    {
                        "claim_id": "claim_1",
                        "text": "x",
                        "severity": "non_trivial",
                        "citation_keys": ["MISSING"],
                    }
                ],
                "citations": {},
            },
            {"name": "background", "text": "t", "claims": [], "citations": {}},
            {"name": "related_work", "text": "t", "claims": [], "citations": {}},
            {"name": "methods", "text": "t", "claims": [], "citations": {}},
            {"name": "comparison", "text": "t", "claims": [], "citations": {}},
            {"name": "gaps", "text": "t", "claims": [], "citations": {}},
            {"name": "conclusions", "text": "t", "claims": [], "citations": {}},
        ],
    }
    report = StructuredReport.model_validate(report_dict)

    with pytest.raises(ClaimPolicyViolationError) as e:
        enforcer.enforce_report(report)

    assert str(e.value) == "Claim references unknown citation_key: claim_id=claim_1 citation_key=MISSING"
