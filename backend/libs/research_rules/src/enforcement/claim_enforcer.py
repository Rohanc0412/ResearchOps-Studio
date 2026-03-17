from __future__ import annotations

from pathlib import Path
from typing import Iterable

import yaml

from src.contracts.artifacts import StructuredReport
from src.contracts.claims import Claim, SystemPolicy
from src.contracts.errors import ClaimPolicyViolationError, ContractError


def load_system_policy(path: str | Path) -> SystemPolicy:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    policy = SystemPolicy.model_validate(raw)
    if policy.fail_closed is not True:
        raise ContractError("Part 1 requires fail_closed=true in policy config")
    return policy


class ClaimEnforcer:
    def __init__(self, policy: SystemPolicy) -> None:
        if policy.fail_closed is not True:
            raise ContractError("ClaimEnforcer requires fail_closed=true")
        self._policy = policy

    def enforce_report(self, report: StructuredReport) -> None:
        for section in report.sections:
            self._enforce_claims(section.claims, section.citations)

    def _enforce_claims(self, claims: Iterable[Claim], citations: dict[str, object]) -> None:
        for claim in claims:
            severity_policy = self._policy.claims.severities[claim.severity]
            if severity_policy.citation_required and len(claim.citation_keys) == 0:
                raise ClaimPolicyViolationError(
                    f"Non-trivial claim requires at least one citation_key: claim_id={claim.claim_id}"
                )
            for key in claim.citation_keys:
                if key not in citations:
                    raise ClaimPolicyViolationError(
                        f"Claim references unknown citation_key: claim_id={claim.claim_id} citation_key={key}"
                    )

