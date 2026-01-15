from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.contracts.evidence import EvidenceSnapshot, EvidenceSnippet
from src.enforcement.evidence_validator import EvidenceStore
from src.utils.hash import sha256_hex


@pytest.fixture()
def evidence_store() -> EvidenceStore:
    store = EvidenceStore()

    raw_text = "Example evidence text used for fixtures. It is immutable."
    snapshot = EvidenceSnapshot(
        snapshot_id="snap_001",
        source_meta="fixture://example",
        content_hash=sha256_hex(raw_text),
        captured_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        raw_text=raw_text,
    )
    store.add_snapshot(snapshot)

    start = 0
    end = 34
    snippet = EvidenceSnippet(
        snippet_id="snip_001",
        snapshot_id="snap_001",
        start_char=start,
        end_char=end,
        snippet_text=raw_text[start:end],
        injection_risk_flag=False,
    )
    store.add_snippet(snippet)
    return store


@pytest.fixture()
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]

