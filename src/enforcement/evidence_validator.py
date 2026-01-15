from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from src.contracts.artifacts import ExperimentPlan, LiteratureMap, StructuredReport
from src.contracts.errors import EvidenceValidationError
from src.contracts.evidence import EvidenceRef, EvidenceSnapshot, EvidenceSnippet, SnippetId
from src.utils.hash import sha256_hex


@dataclass(frozen=True, slots=True)
class EvidenceResolution:
    ref: EvidenceRef
    snippet: EvidenceSnippet
    snapshot: EvidenceSnapshot


class EvidenceStore:
    def __init__(self) -> None:
        self._snapshots: dict[str, EvidenceSnapshot] = {}
        self._snippets: dict[str, EvidenceSnippet] = {}

    def add_snapshot(self, snapshot: EvidenceSnapshot) -> None:
        if snapshot.snapshot_id in self._snapshots:
            raise EvidenceValidationError(f"Duplicate snapshot_id in EvidenceStore: snapshot_id={snapshot.snapshot_id}")
        expected = sha256_hex(snapshot.raw_text)
        if snapshot.content_hash != expected:
            raise EvidenceValidationError(
                f"EvidenceSnapshot content_hash mismatch: snapshot_id={snapshot.snapshot_id}"
            )
        self._snapshots[snapshot.snapshot_id] = snapshot

    def add_snippet(self, snippet: EvidenceSnippet) -> None:
        if snippet.snippet_id in self._snippets:
            raise EvidenceValidationError(f"Duplicate snippet_id in EvidenceStore: snippet_id={snippet.snippet_id}")
        snapshot = self._snapshots.get(snippet.snapshot_id)
        if snapshot is None:
            raise EvidenceValidationError(
                f"Unknown snapshot_id for EvidenceSnippet: snapshot_id={snippet.snapshot_id} snippet_id={snippet.snippet_id}"
            )
        if snippet.end_char > len(snapshot.raw_text):
            raise EvidenceValidationError(
                f"EvidenceSnippet out of bounds: snippet_id={snippet.snippet_id} snapshot_id={snippet.snapshot_id}"
            )
        expected_text = snapshot.raw_text[snippet.start_char : snippet.end_char]
        if snippet.snippet_text != expected_text:
            raise EvidenceValidationError(
                f"EvidenceSnippet snippet_text mismatch: snippet_id={snippet.snippet_id} snapshot_id={snippet.snapshot_id}"
            )
        self._snippets[snippet.snippet_id] = snippet

    def get_snippet(self, snippet_id: SnippetId) -> EvidenceSnippet:
        snippet = self._snippets.get(snippet_id)
        if snippet is None:
            raise EvidenceValidationError(f"Unknown snippet_id in EvidenceStore: snippet_id={snippet_id}")
        return snippet

    def validate_evidence_ref(self, ref: EvidenceRef | dict) -> EvidenceResolution:
        if isinstance(ref, dict) and "snippet_id" not in ref:
            raise EvidenceValidationError("EvidenceRef must include snippet_id (URL-only refs are not allowed)")
        try:
            parsed = ref if isinstance(ref, EvidenceRef) else EvidenceRef.model_validate(ref)
        except ValidationError as e:
            raise EvidenceValidationError(str(e)) from e

        snippet = self.get_snippet(parsed.snippet_id)
        if snippet.snapshot_id != parsed.snapshot_id:
            raise EvidenceValidationError(
                "EvidenceRef snapshot mismatch: "
                f"snippet_id={parsed.snippet_id} ref.snapshot_id={parsed.snapshot_id} snippet.snapshot_id={snippet.snapshot_id}"
            )
        snapshot = self._snapshots.get(parsed.snapshot_id)
        if snapshot is None:
            raise EvidenceValidationError(f"Unknown snapshot_id in EvidenceStore: snapshot_id={parsed.snapshot_id}")

        if parsed.start_char is not None and parsed.end_char is not None:
            if parsed.start_char < snippet.start_char or parsed.end_char > snippet.end_char:
                raise EvidenceValidationError(
                    "EvidenceRef offsets must be within snippet bounds: "
                    f"snippet_id={parsed.snippet_id} start_char={parsed.start_char} end_char={parsed.end_char}"
                )
        return EvidenceResolution(ref=parsed, snippet=snippet, snapshot=snapshot)


class EvidenceValidator:
    @staticmethod
    def validate_report(report: StructuredReport, store: EvidenceStore) -> None:
        for section in report.sections:
            for ref in section.citations.values():
                store.validate_evidence_ref(ref)

    @staticmethod
    def validate_literature_map(lit_map: LiteratureMap, store: EvidenceStore) -> None:
        for node in lit_map.nodes:
            for ref in node.evidence_refs:
                store.validate_evidence_ref(ref)
        for edge in lit_map.edges:
            for ref in edge.evidence_refs:
                store.validate_evidence_ref(ref)

    @staticmethod
    def validate_experiment_plan(plan: ExperimentPlan, store: EvidenceStore) -> None:
        for ds in plan.datasets:
            for ref in ds.evidence_refs:
                store.validate_evidence_ref(ref)
        for model in plan.baseline_models:
            for ref in model.evidence_refs:
                store.validate_evidence_ref(ref)

