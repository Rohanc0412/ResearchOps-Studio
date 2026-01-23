from __future__ import annotations

from typing import Literal

from pydantic import Field

from src.contracts._base import StrictBaseModel

BudgetExhaustionMode = Literal["fail", "finalize_partial"]


class BudgetPolicyConfig(StrictBaseModel):
    exhaustion_mode: BudgetExhaustionMode = "fail"
    max_connector_calls: int = Field(gt=0)
    max_time_seconds: int = Field(gt=0)
    max_tokens: int = Field(gt=0)
    max_retries_per_stage: int = Field(ge=0)
    max_evidence_items_ingested: int = Field(ge=0)


class PartialResult(StrictBaseModel):
    partial: bool = True
    reason: str

