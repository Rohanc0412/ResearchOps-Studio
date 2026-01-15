from __future__ import annotations

import time
from dataclasses import dataclass

from src.contracts.budgets import BudgetPolicyConfig, PartialResult
from src.contracts.errors import BudgetExceededError


@dataclass(frozen=True, slots=True)
class BudgetUsage:
    connector_calls: int = 0
    tokens: int = 0
    evidence_items_ingested: int = 0


class BudgetGuard:
    def __init__(self, policy: BudgetPolicyConfig) -> None:
        self._policy = policy
        self._start = time.monotonic()
        self._connector_calls = 0
        self._tokens = 0
        self._evidence_items_ingested = 0
        self._retries_per_stage: dict[str, int] = {}

    def usage(self) -> BudgetUsage:
        return BudgetUsage(
            connector_calls=self._connector_calls,
            tokens=self._tokens,
            evidence_items_ingested=self._evidence_items_ingested,
        )

    def check_time(self) -> None | PartialResult:
        elapsed = int(time.monotonic() - self._start)
        if elapsed > self._policy.max_time_seconds:
            return self._exhausted("max_time_seconds", self._policy.max_time_seconds, elapsed)
        return None

    def consume_connector_call(self, n: int = 1) -> None | PartialResult:
        if n <= 0:
            raise ValueError("n must be positive")
        self._connector_calls += n
        if self._connector_calls > self._policy.max_connector_calls:
            return self._exhausted("max_connector_calls", self._policy.max_connector_calls, self._connector_calls)
        return None

    def consume_tokens(self, n: int) -> None | PartialResult:
        if n <= 0:
            raise ValueError("n must be positive")
        self._tokens += n
        if self._tokens > self._policy.max_tokens:
            return self._exhausted("max_tokens", self._policy.max_tokens, self._tokens)
        return None

    def ingest_evidence_item(self, n: int = 1) -> None | PartialResult:
        if n <= 0:
            raise ValueError("n must be positive")
        self._evidence_items_ingested += n
        if self._evidence_items_ingested > self._policy.max_evidence_items_ingested:
            return self._exhausted(
                "max_evidence_items_ingested",
                self._policy.max_evidence_items_ingested,
                self._evidence_items_ingested,
            )
        return None

    def record_retry(self, stage: str) -> None | PartialResult:
        stage = stage.strip()
        if not stage:
            raise ValueError("stage must be non-empty")
        self._retries_per_stage[stage] = self._retries_per_stage.get(stage, 0) + 1
        used = self._retries_per_stage[stage]
        if used > self._policy.max_retries_per_stage:
            return self._exhausted("max_retries_per_stage", self._policy.max_retries_per_stage, used)
        return None

    def _exhausted(self, budget_name: str, limit: int, used: int) -> None | PartialResult:
        if self._policy.exhaustion_mode == "fail":
            raise BudgetExceededError(budget_name=budget_name, limit=limit, used=used)
        return PartialResult(reason=f"Budget exceeded: {budget_name} limit={limit} used={used}")

