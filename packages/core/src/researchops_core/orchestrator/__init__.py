"""
Orchestrator package for LangGraph-based multi-agent workflow.

Provides:
- OrchestratorState: Central state container
- Type definitions for all data structures
- Event emission utilities
"""

from __future__ import annotations

from researchops_core.orchestrator.state import (
    Claim,
    EvaluatorDecision,
    EvidenceSnippetRef,
    FactCheckResult,
    OrchestratorState,
    OutlineModel,
    OutlineSection,
    RepairPlan,
    SourceRef,
    ValidationError,
)

__all__ = [
    "OrchestratorState",
    "SourceRef",
    "EvidenceSnippetRef",
    "OutlineSection",
    "OutlineModel",
    "Claim",
    "FactCheckResult",
    "ValidationError",
    "RepairPlan",
    "EvaluatorDecision",
]
