from __future__ import annotations

import pytest

from src.contracts.budgets import BudgetPolicyConfig, PartialResult
from src.contracts.errors import BudgetExceededError
from src.enforcement.budget_guard import BudgetGuard


def test_budget_exhaustion_fail_mode_raises() -> None:
    policy = BudgetPolicyConfig(
        exhaustion_mode="fail",
        max_connector_calls=1,
        max_time_seconds=999,
        max_tokens=1,
        max_retries_per_stage=0,
        max_evidence_items_ingested=0,
    )
    guard = BudgetGuard(policy)
    with pytest.raises(BudgetExceededError) as e:
        guard.consume_tokens(2)
    assert str(e.value) == "Budget exceeded: max_tokens limit=1 used=2"


def test_budget_exhaustion_finalize_partial_returns_partial_result() -> None:
    policy = BudgetPolicyConfig(
        exhaustion_mode="finalize_partial",
        max_connector_calls=1,
        max_time_seconds=999,
        max_tokens=1,
        max_retries_per_stage=0,
        max_evidence_items_ingested=0,
    )
    guard = BudgetGuard(policy)
    result = guard.consume_tokens(2)
    assert isinstance(result, PartialResult)
    assert result.partial is True
    assert result.reason == "Budget exceeded: max_tokens limit=1 used=2"

