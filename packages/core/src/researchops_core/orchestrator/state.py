"""
State definitions for the orchestrator graph.

The OrchestratorState is the central container passed through all nodes.
All data structures are Pydantic models for validation and serialization.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    """Reference to a retrieved source."""

    source_id: UUID
    canonical_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    url: str | None = None
    pdf_url: str | None = None
    connector: str
    quality_score: float = 0.0  # 0.0-1.0, set by SourceVetter


class EvidenceSnippetRef(BaseModel):
    """Reference to an evidence snippet."""

    snippet_id: UUID
    source_id: UUID
    text: str
    char_start: int
    char_end: int
    embedding_vector: list[float] | None = None  # Optional, not always needed


class OutlineSection(BaseModel):
    """A section in the outline."""

    section_id: str  # e.g. "1", "1.1", "2.3.1"
    title: str
    description: str
    required_evidence: list[str] = Field(default_factory=list)  # Queries for this section


class OutlineModel(BaseModel):
    """Structured outline for the report."""

    sections: list[OutlineSection]
    total_estimated_words: int = 3000


class Claim(BaseModel):
    """An atomic claim extracted from the draft."""

    claim_id: str  # e.g. "claim_1", "claim_2"
    text: str
    section_id: str | None = None
    citation_ids: list[str] = Field(default_factory=list)  # [CITE:snippet_id]
    requires_evidence: bool = True


class FactCheckStatus(str, Enum):
    """Status of fact checking."""

    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient"
    NOT_CHECKED = "not_checked"


class FactCheckResult(BaseModel):
    """Result of fact-checking a claim."""

    claim_id: str
    status: FactCheckStatus
    supporting_snippets: list[UUID] = Field(default_factory=list)
    contradicting_snippets: list[UUID] = Field(default_factory=list)
    confidence: float = 0.0  # 0.0-1.0
    explanation: str = ""


class ValidationErrorType(str, Enum):
    """Type of validation error."""

    MISSING_CITATION = "missing_citation"
    INVALID_CITATION = "invalid_citation"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    CONTRADICTED_CLAIM = "contradicted_claim"


class ValidationError(BaseModel):
    """A validation error found in the draft."""

    error_type: ValidationErrorType
    claim_id: str | None = None
    section_id: str | None = None
    citation_id: str | None = None
    description: str
    severity: str = "error"  # "error" or "warning"


class RepairPlan(BaseModel):
    """Plan for repairing validation errors."""

    target_claims: list[str] = Field(default_factory=list)  # Claims to fix
    target_sections: list[str] = Field(default_factory=list)  # Sections to rewrite
    strategy: str = ""  # Description of repair strategy
    additional_evidence_needed: bool = False


class EvaluatorDecision(str, Enum):
    """Evaluator decision on whether to continue."""

    STOP_SUCCESS = "stop_success"  # All good, export
    CONTINUE_REPAIR = "continue_repair"  # Errors found, repair needed
    CONTINUE_RETRIEVE = "continue_retrieve"  # Need more evidence
    CONTINUE_REWRITE = "continue_rewrite"  # Need better draft


class OrchestratorState(BaseModel):
    """
    Central state container for the orchestrator graph.

    This is passed through all nodes and updated incrementally.
    All fields are optional to support incremental construction.
    """

    # Identity
    tenant_id: UUID
    run_id: UUID
    project_id: UUID | None = None

    # Input
    user_query: str
    research_goal: str | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    llm_provider: str | None = None
    llm_model: str | None = None

    # Stage 1: Question generation
    generated_queries: list[str] = Field(default_factory=list)

    # Stage 2: Retrieval
    retrieved_sources: list[SourceRef] = Field(default_factory=list)
    evidence_snippets: list[EvidenceSnippetRef] = Field(default_factory=list)

    # Stage 3: Source vetting
    vetted_sources: list[SourceRef] = Field(default_factory=list)

    # Stage 4: Outlining
    outline: OutlineModel | None = None

    # Stage 5: Writing
    draft_text: str = ""
    draft_version: int = 0

    # Stage 6: Claim extraction
    extracted_claims: list[Claim] = Field(default_factory=list)

    # Stage 7: Citation validation
    citation_errors: list[ValidationError] = Field(default_factory=list)

    # Stage 8: Fact checking
    fact_check_results: list[FactCheckResult] = Field(default_factory=list)

    # Stage 9: Repair
    repair_plan: RepairPlan | None = None
    repair_attempts: int = 0
    max_repair_attempts: int = 3

    # Stage 10: Export
    artifacts: dict[str, Any] = Field(default_factory=dict)  # filename -> content

    # Stage 11: Evaluation
    evaluator_decision: EvaluatorDecision | None = None
    evaluation_reason: str = ""

    # Metadata
    iteration_count: int = 0
    max_iterations: int = 5
    started_at: datetime | None = None
    completed_at: datetime | None = None

    class Config:
        """Pydantic config."""

        arbitrary_types_allowed = True
