from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from src.contracts._base import StrictBaseModel

ClaimSeverity = Literal["trivial", "non_trivial"]

ClaimId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=64,
        pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{2,63}$",
    ),
]

CitationKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.:-]{1,64}$",
    ),
]


class Claim(StrictBaseModel):
    claim_id: ClaimId
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000)]
    severity: ClaimSeverity
    citation_keys: list[CitationKey] = Field(default_factory=list)

    @field_validator("citation_keys")
    @classmethod
    def _unique_citation_keys(cls, value: list[CitationKey]) -> list[CitationKey]:
        seen: set[str] = set()
        duplicates: list[str] = []
        for key in value:
            if key in seen:
                duplicates.append(key)
            seen.add(key)
        if duplicates:
            raise ValueError(f"Duplicate citation_keys: {sorted(set(duplicates))}")
        return value


class ClaimSeverityPolicy(StrictBaseModel):
    citation_required: bool


class ClaimsPolicy(StrictBaseModel):
    severities: dict[ClaimSeverity, ClaimSeverityPolicy]


class SystemPolicy(StrictBaseModel):
    fail_closed: bool = True
    claims: ClaimsPolicy
    budgets: "BudgetPolicyConfig"


from src.contracts.budgets import BudgetPolicyConfig  # noqa: E402  (circular types only)

