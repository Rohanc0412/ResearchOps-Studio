from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from src.contracts._base import StrictBaseModel
from src.contracts.claims import Claim
from src.contracts.evidence import EvidenceRef

NodeType = Literal["paper", "dataset", "code"]
EdgeType = Literal["cites", "extends", "compares", "critiques"]

NodeId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=64,
        pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{2,63}$",
    ),
]


class LiteratureNode(StrictBaseModel):
    node_id: NodeId
    type: NodeType
    metadata: dict[str, Any]
    score: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[EvidenceRef]


class LiteratureEdge(StrictBaseModel):
    edge_id: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=3,
            max_length=64,
            pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{2,63}$",
        ),
    ]
    type: EdgeType
    from_node_id: NodeId
    to_node_id: NodeId
    evidence_refs: list[EvidenceRef]


class LiteratureMap(StrictBaseModel):
    artifact_type: Literal["literature_map"] = "literature_map"
    nodes: list[LiteratureNode]
    edges: list[LiteratureEdge]

    @model_validator(mode="after")
    def _validate_graph(self) -> "LiteratureMap":
        node_ids = [n.node_id for n in self.nodes]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("LiteratureMap node_ids must be unique")
        known = set(node_ids)
        for edge in self.edges:
            if edge.from_node_id not in known or edge.to_node_id not in known:
                raise ValueError(
                    f"LiteratureMap edge references unknown node id: edge_id={edge.edge_id}"
                )
        return self


ReportSectionName = Literal[
    "intro",
    "background",
    "related_work",
    "methods",
    "comparison",
    "gaps",
    "conclusions",
]

REQUIRED_REPORT_SECTION_ORDER: list[ReportSectionName] = [
    "intro",
    "background",
    "related_work",
    "methods",
    "comparison",
    "gaps",
    "conclusions",
]


class ReportSection(StrictBaseModel):
    name: ReportSectionName
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200_000)]
    claims: list[Claim]
    citations: dict[str, EvidenceRef]

    @field_validator("citations")
    @classmethod
    def _citation_keys_valid(cls, value: dict[str, EvidenceRef]) -> dict[str, EvidenceRef]:
        for k in value.keys():
            if not isinstance(k, str) or not k.strip():
                raise ValueError("citations keys must be non-empty strings")
        return value


class StructuredReport(StrictBaseModel):
    artifact_type: Literal["structured_report"] = "structured_report"
    sections: list[ReportSection]

    @model_validator(mode="after")
    def _enforce_section_order(self) -> "StructuredReport":
        names: list[ReportSectionName] = [s.name for s in self.sections]
        if names != REQUIRED_REPORT_SECTION_ORDER:
            raise ValueError(
                "StructuredReport sections must be in strict order: "
                + ", ".join(REQUIRED_REPORT_SECTION_ORDER)
            )
        return self


class DatasetSpec(StrictBaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000)]
    evidence_refs: list[EvidenceRef]


class ModelSpec(StrictBaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000)]
    evidence_refs: list[EvidenceRef]


class ExperimentPlan(StrictBaseModel):
    artifact_type: Literal["experiment_plan"] = "experiment_plan"
    hypothesis: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)]
    datasets: list[DatasetSpec] = Field(min_length=1)
    baseline_models: list[ModelSpec] = Field(min_length=1)
    evaluation_metrics: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]] = (
        Field(min_length=1)
    )
    ablation_plan: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)]
    compute_estimation: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)]
    risks_and_failure_cases: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)]
    ] = Field(min_length=1)
