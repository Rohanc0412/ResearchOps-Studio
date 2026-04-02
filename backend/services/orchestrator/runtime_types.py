from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ResearchRunInputs:
    user_query: str
    research_goal: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    stage_models: dict[str, str | None] = field(default_factory=dict)
    max_iterations: int = 5


__all__ = ["ResearchRunInputs"]
