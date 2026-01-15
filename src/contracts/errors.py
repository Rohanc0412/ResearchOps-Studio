from __future__ import annotations


class ContractError(Exception):
    pass


class ClaimPolicyViolationError(ContractError):
    pass


class EvidenceValidationError(ContractError):
    pass


class BudgetExceededError(ContractError):
    def __init__(self, *, budget_name: str, limit: int, used: int) -> None:
        self.budget_name = budget_name
        self.limit = limit
        self.used = used
        super().__init__(f"Budget exceeded: {budget_name} limit={limit} used={used}")

