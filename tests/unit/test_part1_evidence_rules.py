from __future__ import annotations

import pytest

from src.contracts.evidence import EvidenceRef
from src.contracts.errors import EvidenceValidationError


def test_evidence_ref_snippet_id_missing_in_store_fails_closed(evidence_store) -> None:
    ref = EvidenceRef(snapshot_id="snap_001", snippet_id="snip_missing")
    with pytest.raises(EvidenceValidationError) as e:
        evidence_store.validate_evidence_ref(ref)
    assert str(e.value) == "Unknown snippet_id in EvidenceStore: snippet_id=snip_missing"


def test_evidence_ref_missing_snippet_id_url_only_fails_closed(evidence_store) -> None:
    with pytest.raises(EvidenceValidationError) as e:
        evidence_store.validate_evidence_ref({"snapshot_id": "snap_001", "url": "https://example.com"})
    assert str(e.value) == "EvidenceRef must include snippet_id (URL-only refs are not allowed)"

